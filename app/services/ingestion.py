"""Layer 1 Ingestion Service implementation with Layer 10 Security integration."""

import configparser
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from app.core.config import get_settings
from app.models.ingestion import (
    FileNode,
    GitHubAPIError,
    IngestionLimitExceededError,
    IngestionResult,
    InvalidURLError,
    RepoMetadata,
    RepoTooLargeError,
    SkippedItem,
)
from app.security.path_hardening import PathHardeningError, validate_path_depth_and_length
from app.security.secret_scanner import SecretScanner
from app.services.security import run_sandboxed_git_command, sandbox_workspace
from app.utils.file_filter import (
    BINARY_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    is_binary_file,
    is_ignored_directory,
    sanitize_and_validate_subpath,
    should_include_relative_path,
    validate_safe_path,
)
from app.utils.url_validator import (
    check_repo_reachability,
    validate_github_url,
    validate_ssrf,
)

MAX_REPO_FILE_LIMIT_V1 = 150


def check_repo_size_preflight(
    github_url: str,
    commit_ref: Optional[str] = None,
    subpath: Optional[str] = None,
    max_file_limit: int = MAX_REPO_FILE_LIMIT_V1,
    timeout_seconds: float = 12.0,
    github_token: Optional[str] = None,
) -> int:
    """
    Performs a lightweight preflight check of the target repository file count
    using the GitHub Git Trees API without cloning the repository.
    Respects branch/commit ref and subpath scoping.

    Returns:
        int: Number of valid supported files found under the scoped path/ref.

    Raises:
        InvalidURLError: URL is invalid or subpath contains path traversal / null bytes.
        SSRFError: Hostname fails SSRF checks.
        RepoTooLargeError: Count exceeds max_file_limit.
        GitHubAPIError: Rate limit, 404, private repo, auth error, or network failure.
    """
    owner, repo = validate_github_url(github_url)
    validate_ssrf("github.com")

    try:
        clean_subpath = sanitize_and_validate_subpath(subpath)
    except ValueError as e:
        raise InvalidURLError(str(e))

    tree_sha = commit_ref.strip() if commit_ref and commit_ref.strip() else "HEAD"

    headers = {
        "User-Agent": "Backtrace-Preflight/1.0",
        "Accept": "application/vnd.github.v3+json",
    }
    settings = get_settings()
    token = (
        github_token
        or getattr(settings, "GITHUB_TOKEN", None)
        or getattr(settings, "GITHUB_PAT", None)
        or os.getenv("GITHUB_TOKEN")
        or os.getenv("GITHUB_PAT")
        or os.getenv("GH_TOKEN")
    )
    is_authenticated = bool(token)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            resp = client.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1",
                headers=headers,
            )

            # If HEAD returned 404/422, try resolving default branch
            if resp.status_code in (404, 422) and tree_sha == "HEAD":
                repo_resp = client.get(
                    f"https://api.github.com/repos/{owner}/{repo}",
                    headers=headers,
                )
                if repo_resp.status_code == 200:
                    default_branch = repo_resp.json().get("default_branch", "main")
                    resp = client.get(
                        f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1",
                        headers=headers,
                    )
                elif repo_resp.status_code == 404:
                    raise GitHubAPIError(
                        "GitHub repository not found or repository is private (HTTP 404).",
                        status_code=404,
                    )
                elif repo_resp.status_code in (403, 429):
                    rate_msg = (
                        "GitHub API rate limit exceeded on configured token. Please try again later."
                        if is_authenticated
                        else "GitHub API rate limit exceeded (unauthenticated requests are limited to 60/hr). Please configure a GITHUB_TOKEN in your environment or retry shortly."
                    )
                    raise GitHubAPIError(rate_msg, status_code=repo_resp.status_code)
                elif repo_resp.status_code == 401:
                    raise GitHubAPIError(
                        "GitHub API authentication failed (HTTP 401).",
                        status_code=401,
                    )
                else:
                    raise GitHubAPIError(
                        f"GitHub API query failed with HTTP {repo_resp.status_code}.",
                        status_code=repo_resp.status_code,
                    )

            if resp.status_code == 404:
                raise GitHubAPIError(
                    f"Repository or ref '{tree_sha}' not found on GitHub (HTTP 404).",
                    status_code=404,
                )
            elif resp.status_code in (403, 429):
                rate_msg = (
                    "GitHub API rate limit exceeded on configured token. Please try again later."
                    if is_authenticated
                    else "GitHub API rate limit exceeded (unauthenticated requests are limited to 60/hr). Please configure a GITHUB_TOKEN in your environment or retry shortly."
                )
                raise GitHubAPIError(rate_msg, status_code=resp.status_code)
            elif resp.status_code == 401:
                raise GitHubAPIError(
                    "GitHub API authentication failed (HTTP 401).",
                    status_code=401,
                )
            elif resp.status_code != 200:
                raise GitHubAPIError(
                    f"GitHub API returned unexpected status {resp.status_code}.",
                    status_code=resp.status_code,
                )

            data = resp.json()
            tree_items = data.get("tree", [])

            file_count = 0
            for item in tree_items:
                if item.get("type") != "blob":
                    continue
                p = item.get("path", "")
                size = item.get("size")

                # Apply unified inclusion rules
                include, _ = should_include_relative_path(
                    rel_path=p,
                    subpath=clean_subpath,
                    size_bytes=size,
                )
                if not include:
                    continue

                file_count += 1

            if file_count > max_file_limit:
                raise RepoTooLargeError(
                    f"Found {file_count} supported files (limit: {max_file_limit} files)",
                    file_count=file_count,
                    limit=max_file_limit,
                )

            return file_count

    except httpx.RequestError as e:
        raise GitHubAPIError(f"Failed to connect to GitHub API: {e}")


class IngestionService:
    """Service orchestrating safe GitHub repository ingestion."""

    def __init__(self, max_file_limit: int = MAX_REPO_FILE_LIMIT_V1, timeout_seconds: float = 60.0):
        self.max_file_limit = max_file_limit
        self.timeout_seconds = timeout_seconds
        self.secret_scanner = SecretScanner()

    def ingest_repository(
        self,
        github_url: str,
        commit_ref: Optional[str] = None,
        subpath: Optional[str] = None,
    ) -> IngestionResult:
        """
        Ingests a public GitHub repository. Validates URL, checks SSRF,
        executes sandboxed clone without hooks, filters files, redacts secrets,
        and returns the file tree, text contents, skipped items, and metadata.
        Respects commit_ref and subpath scoping.
        """
        # Step 1: Input & Security Validation
        owner, repo_name = validate_github_url(github_url)
        validated_ip = validate_ssrf("github.com")
        check_repo_reachability(github_url)

        try:
            clean_subpath = sanitize_and_validate_subpath(subpath)
        except ValueError as e:
            raise InvalidURLError(str(e))

        start_time = time.time()

        # Step 2: Isolated Sandboxed Execution
        with sandbox_workspace() as clone_dir:
            # 2a. Full clone with --no-checkout
            run_sandboxed_git_command(
                ["clone", "--no-checkout", github_url, "."],
                cwd=clone_dir,
                timeout_seconds=self.timeout_seconds,
            )

            # 2b. Checkout specified ref or HEAD
            target_ref = commit_ref.strip() if commit_ref and commit_ref.strip() else "HEAD"
            try:
                run_sandboxed_git_command(
                    ["checkout", target_ref],
                    cwd=clone_dir,
                    timeout_seconds=self.timeout_seconds,
                )
            except Exception:
                if target_ref != "HEAD":
                    run_sandboxed_git_command(
                        ["checkout", "HEAD"],
                        cwd=clone_dir,
                        timeout_seconds=self.timeout_seconds,
                    )
                else:
                    raise

            clone_duration = round(time.time() - start_time, 2)

            # Step 3: Extract Metadata & History Signals
            head_commit = self._get_head_commit(clone_dir)
            default_branch = self._get_default_branch(clone_dir)
            submodule_urls, submodule_skipped = self._parse_gitmodules(clone_dir)

            # Step 4: Walk File Tree and Apply Security & Filtering Rules
            file_tree, file_contents, skipped_items = self._process_file_tree(
                clone_dir, subpath=clean_subpath
            )

            if submodule_skipped and not clean_subpath:
                skipped_items.append(submodule_skipped)

            repo_metadata = RepoMetadata(
                default_branch=default_branch,
                head_commit=head_commit,
                clone_duration_seconds=clone_duration,
                submodule_urls=submodule_urls,
            )

            return IngestionResult(
                file_tree=file_tree,
                file_contents=file_contents,
                skipped_items=skipped_items,
                metadata=repo_metadata,
            )


    def _get_head_commit(self, repo_dir: Path) -> str:
        res = run_sandboxed_git_command(["rev-parse", "HEAD"], cwd=repo_dir)
        return res.stdout.strip()

    def _get_default_branch(self, repo_dir: Path) -> str:
        try:
            res = run_sandboxed_git_command(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)
            branch = res.stdout.strip()
            return branch if branch != "HEAD" else "main"
        except Exception:
            return "main"

    def _parse_gitmodules(self, repo_dir: Path) -> Tuple[List[str], Optional[SkippedItem]]:
        """Parses .gitmodules if present to log submodule URLs without fetching them."""
        gitmodules_path = repo_dir / ".gitmodules"
        if not gitmodules_path.exists():
            return [], None

        submodule_urls = []
        try:
            config = configparser.ConfigParser()
            config.read(gitmodules_path, encoding="utf-8")
            for section in config.sections():
                if config.has_option(section, "url"):
                    submodule_urls.append(config.get(section, "url"))
        except Exception:
            pass

        skipped = SkippedItem(
            path=".gitmodules",
            reason="skipped — submodule reference file recorded as metadata without fetching",
        )
        return submodule_urls, skipped

    def _process_file_tree(
        self, base_dir: Path, subpath: Optional[str] = None
    ) -> Tuple[List[FileNode], Dict[str, str], List[SkippedItem]]:
        file_tree: List[FileNode] = []
        file_contents: Dict[str, str] = {}
        skipped_items: List[SkippedItem] = []

        valid_file_count = 0

        for root, dirs, files in os.walk(base_dir, followlinks=False):
            rel_root = Path(root).relative_to(base_dir)

            # Filter ignored directories in-place during walk
            dirs[:] = [d for d in dirs if not is_ignored_directory(d)]

            for file_name in files:
                abs_path = Path(root) / file_name
                rel_path = str((rel_root / file_name).as_posix())

                # 1. Symlink detection
                if abs_path.is_symlink() or os.path.islink(abs_path):
                    skipped_items.append(
                        SkippedItem(path=rel_path, reason="skipped — symlink")
                    )
                    continue

                # 2. File size read
                try:
                    file_size = abs_path.stat().st_size
                except OSError:
                    skipped_items.append(
                        SkippedItem(path=rel_path, reason="skipped — unreadable file stats")
                    )
                    continue

                # 3. Unified filtering rule
                include, reason = should_include_relative_path(
                    rel_path=rel_path,
                    subpath=subpath,
                    size_bytes=file_size,
                )
                if not include:
                    if reason:
                        skipped_items.append(SkippedItem(path=rel_path, reason=reason))
                    continue

                # 4. Path traversal guard
                if not validate_safe_path(abs_path, base_dir):
                    skipped_items.append(
                        SkippedItem(path=rel_path, reason="skipped — path traversal detected")
                    )
                    continue

                # 5. Path depth and filename length guard
                try:
                    validate_path_depth_and_length(Path(rel_path))
                except PathHardeningError as e:
                    skipped_items.append(
                        SkippedItem(path=rel_path, reason=f"skipped — {e}")
                    )
                    continue

                # 6. Binary file content sniffing check
                if is_binary_file(abs_path):
                    skipped_items.append(
                        SkippedItem(path=rel_path, reason="skipped — binary file")
                    )
                    continue

                # 7. File count limit check
                valid_file_count += 1
                if valid_file_count > self.max_file_limit:
                    raise IngestionLimitExceededError(
                        f"Repository file count exceeds maximum allowed cap of {self.max_file_limit} files for v1."
                    )

                # 8. Read text content safely and redact secrets
                try:
                    text = abs_path.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    skipped_items.append(
                        SkippedItem(path=rel_path, reason=f"skipped — text decode error: {e}")
                    )
                    valid_file_count -= 1
                    continue

                # Scan and redact any sensitive secrets in place
                redacted_text, file_redactions = self.secret_scanner.scan_and_redact(text)

                ext = abs_path.suffix.lower()
                file_tree.append(
                    FileNode(
                        path=rel_path,
                        size_bytes=file_size,
                        extension=ext,
                        file_type="file",
                        redaction_count=file_redactions,
                    )
                )
                file_contents[rel_path] = redacted_text

        return file_tree, file_contents, skipped_items
