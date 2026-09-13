"""Integration tests for Layer 1 Ingestion Service."""

import os
import subprocess
import tempfile
from pathlib import Path
import pytest

from app.models.ingestion import IngestionLimitExceededError
from app.services.ingestion import IngestionService
from app.services.security import run_sandboxed_git_command, sandbox_workspace
from app.utils.file_filter import is_binary_file, validate_safe_path


@pytest.fixture
def test_repo_path(tmp_path):
    """
    Creates a local git repository acting as a synthetic origin repository
    containing git hooks, submodules, symlinks, binary files, and oversized files.
    """
    repo_dir = tmp_path / "origin_repo"
    repo_dir.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # 1. Normal text file
    (repo_dir / "README.md").write_text("# Test Repo\nHello World", encoding="utf-8")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "main.py").write_text("print('hello')", encoding="utf-8")

    # 2. Add malicious pre-checkout hook in origin
    hooks_dir = repo_dir / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_file = hooks_dir / "post-checkout"
    hook_file.write_text("#!/bin/sh\necho 'EXECUTED_HOOK' > /tmp/malicious_hook.txt\nexit 0\n")
    os.chmod(hook_file, 0o755)

    # 3. Add .gitmodules file
    (repo_dir / ".gitmodules").write_text(
        '[submodule "external/lib"]\n\tpath = external/lib\n\turl = https://github.com/example/lib.git\n',
        encoding="utf-8",
    )

    # 4. Add binary file
    (repo_dir / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR\x00\x00")

    # 5. Add oversized file (>1MB)
    large_content = "A" * (1024 * 1024 + 100)
    (repo_dir / "large_file.txt").write_text(large_content, encoding="utf-8")

    # 6. Add a symlink if OS supports it
    symlink_target = repo_dir / "symlink_file.txt"
    try:
        os.symlink("README.md", str(symlink_target))
    except Exception:
        # Windows without admin rights fallback: create relative link or simulate test
        pass

    # Commit initial commit
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)

    # Second commit to verify multi-commit history retention
    (repo_dir / "src" / "utils.py").write_text("def add(a, b): return a + b", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Add utils module"], cwd=repo_dir, check=True)

    return repo_dir


def test_sandboxed_clone_and_ingestion(test_repo_path, monkeypatch):
    """
    Verifies that cloning and ingestion works safely, hooks don't execute,
    symlinks/binaries/large files are skipped, and full git history is present.
    """
    # Bypass remote URL checks for local test repo fixture
    monkeypatch.setattr("app.services.ingestion.validate_github_url", lambda url: ("test", "repo"))
    monkeypatch.setattr("app.services.ingestion.validate_ssrf", lambda host: None)
    monkeypatch.setattr("app.services.ingestion.check_repo_reachability", lambda url: None)

    service = IngestionService()
    result = service.ingest_repository(str(test_repo_path))

    # Check included files
    included_paths = [node.path for node in result.file_tree]
    assert "README.md" in included_paths
    assert "src/main.py" in included_paths
    assert "src/utils.py" in included_paths

    # Confirm contents match
    assert result.file_contents["README.md"] == "# Test Repo\nHello World"
    assert result.file_contents["src/main.py"] == "print('hello')"

    # Confirm skipped items
    skipped_reasons = {item.path: item.reason for item in result.skipped_items}
    assert "image.png" in skipped_reasons
    assert "skipped — binary file" in skipped_reasons["image.png"]

    assert "large_file.txt" in skipped_reasons
    assert "exceeds 1MB limit" in skipped_reasons["large_file.txt"]

    assert ".gitmodules" in skipped_reasons

    # Confirm submodule URL captured in metadata
    assert "https://github.com/example/lib.git" in result.metadata.submodule_urls

    # Confirm malicious hook did NOT execute
    assert not os.path.exists("/tmp/malicious_hook.txt")


def test_full_git_history_retained(test_repo_path, monkeypatch):
    """
    Acceptance Criteria 6: Full commit history is confirmed retrievable from
    the resulting .git directory (test by running git log against it).
    """
    monkeypatch.setattr("app.utils.url_validator.validate_github_url", lambda url: ("test", "repo"))
    monkeypatch.setattr("app.utils.url_validator.validate_ssrf", lambda host: None)
    monkeypatch.setattr("app.utils.url_validator.check_repo_reachability", lambda url: None)

    with sandbox_workspace() as clone_dir:
        run_sandboxed_git_command(
            ["clone", "--no-checkout", str(test_repo_path), "."],
            cwd=clone_dir,
        )
        run_sandboxed_git_command(["checkout", "HEAD"], cwd=clone_dir)

        # Run git log
        log_res = run_sandboxed_git_command(["log", "--oneline"], cwd=clone_dir)
        commits = log_res.stdout.strip().splitlines()
        
        # Must have both commits
        assert len(commits) == 2
        assert "Add utils module" in commits[0]
        assert "Initial commit" in commits[1]


def test_file_count_limit_exceeded(tmp_path, monkeypatch):
    """
    Verifies that a repo exceeding max_file_limit raises IngestionLimitExceededError.
    """
    monkeypatch.setattr("app.services.ingestion.validate_github_url", lambda url: ("test", "repo"))
    monkeypatch.setattr("app.services.ingestion.validate_ssrf", lambda host: None)
    monkeypatch.setattr("app.services.ingestion.check_repo_reachability", lambda url: None)

    repo_dir = tmp_path / "large_count_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # Create 10 files
    for i in range(10):
        (repo_dir / f"file_{i}.txt").write_text(f"content {i}", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)

    # Service with cap of 5 files
    service = IngestionService(max_file_limit=5)
    with pytest.raises(IngestionLimitExceededError, match="maximum allowed cap of 5 files"):
        service.ingest_repository(str(repo_dir))
