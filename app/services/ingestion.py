"""Layer 1 Ingestion Service implementation with Layer 10 Security integration."""

import configparser
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.models.ingestion import (
    FileNode,
    IngestionLimitExceededError,
    IngestionResult,
    RepoMetadata,
    SkippedItem,
)
from app.security.path_hardening import PathHardeningError, validate_path_depth_and_length
from app.security.secret_scanner import SecretScanner
from app.services.security import run_sandboxed_git_command, sandbox_workspace
from app.utils.file_filter import (
    MAX_FILE_SIZE_BYTES,
    is_binary_file,
    is_ignored_directory,
    validate_safe_path,
)
from app.utils.url_validator import (
    check_repo_reachability,
    validate_github_url,
    validate_ssrf,
)

MAX_REPO_FILE_LIMIT_V1 = 150


class IngestionService:
    """Service orchestrating safe GitHub repository ingestion."""

    def __init__(self, max_file_limit: int = MAX_REPO_FILE_LIMIT_V1, timeout_seconds: float = 60.0):
        self.max_file_limit = max_file_limit
        self.timeout_seconds = timeout_seconds
        self.secret_scanner = SecretScanner()

    def ingest_repository(self, github_url: str) -> IngestionResult:
        """
        Ingests a public GitHub repository. Validates URL, checks SSRF,
        executes sandboxed clone without hooks, filters files, redacts secrets,
        and returns the file tree, text contents, skipped items, and metadata.
        """
        # Step 1: Input & Security Validation
        owner, repo_name = validate_github_url(github_url)
        validated_ip = validate_ssrf("github.com")
        check_repo_reachability(github_url)

        start_time = time.time()

        # Step 2: Isolated Sandboxed Execution
        with sandbox_workspace() as clone_dir:
            # 2a. Full clone with --no-checkout
            run_sandboxed_git_command(
                ["clone", "--no-checkout", github_url, "."],
                cwd=clone_dir,
                timeout_seconds=self.timeout_seconds,
            )

            # 2b. Checkout HEAD only
            run_sandboxed_git_command(
                ["checkout", "HEAD"],
                cwd=clone_dir,
                timeout_seconds=self.timeout_seconds,
            )

            clone_duration = round(time.time() - start_time, 2)

            # Step 3: Extract Metadata & History Signals
            head_commit = self._get_head_commit(clone_dir)
            default_branch = self._get_default_branch(clone_dir)
            submodule_urls, submodule_skipped = self._parse_gitmodules(clone_dir)

            # Step 4: Walk File Tree and Apply Security & Filtering Rules
            file_tree, file_contents, skipped_items = self._process_file_tree(clone_dir)

            if submodule_skipped:
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
        self, base_dir: Path
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

                if rel_path == ".gitmodules":
                    continue

                # 1. Path traversal guard
                if not validate_safe_path(abs_path, base_dir):
                    skipped_items.append(
                        SkippedItem(path=rel_path, reason="skipped — path traversal detected")
                    )
                    continue

                # 2. Path depth and filename length guard
                try:
                    validate_path_depth_and_length(Path(rel_path))
                except PathHardeningError as e:
                    skipped_items.append(
                        SkippedItem(path=rel_path, reason=f"skipped — {e}")
                    )
                    continue

                # 3. Symlink detection
                if abs_path.is_symlink() or os.path.islink(abs_path):
                    skipped_items.append(
                        SkippedItem(path=rel_path, reason="skipped — symlink")
                    )
                    continue

                # 4. File size limit
                try:
                    file_size = abs_path.stat().st_size
                except OSError:
                    skipped_items.append(
                        SkippedItem(path=rel_path, reason="skipped — unreadable file stats")
                    )
                    continue

                if file_size > MAX_FILE_SIZE_BYTES:
                    skipped_items.append(
                        SkippedItem(
                            path=rel_path,
                            reason=f"skipped — file size ({file_size} bytes) exceeds 1MB limit",
                        )
                    )
                    continue

                # 5. Binary file check
                if is_binary_file(abs_path):
                    skipped_items.append(
                        SkippedItem(path=rel_path, reason="skipped — binary file")
                    )
                    continue

                # 6. File count limit check
                valid_file_count += 1
                if valid_file_count > self.max_file_limit:
                    raise IngestionLimitExceededError(
                        f"Repository file count exceeds maximum allowed cap of {self.max_file_limit} files for v1."
                    )

                # 7. Read text content safely and redact secrets
                try:
                    text = abs_path.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    skipped_items.append(
                        SkippedItem(path=rel_path, reason=f"skipped — text decode error: {e}")
                    )
                    valid_file_count -= 1
                    continue

                # Scan and redact any sensitive secrets in place
                redacted_text, _ = self.secret_scanner.scan_and_redact(text)

                ext = abs_path.suffix.lower()
                file_tree.append(
                    FileNode(
                        path=rel_path,
                        size_bytes=file_size,
                        extension=ext,
                        file_type="file",
                    )
                )
                file_contents[rel_path] = redacted_text

        return file_tree, file_contents, skipped_items
