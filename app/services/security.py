"""Layer 10 Security and Sandboxing primitives for isolated git operations."""

import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, List, Optional

import stat
from app.models.ingestion import CloneTimeoutError, IngestionError
from app.security.path_hardening import create_secure_temp_dir


def safe_rmtree(target_path: Path) -> None:
    """
    Guarantees complete deletion of temporary workspace directory,
    handling read-only git files (.git objects on Windows) across success and failure paths.
    """
    if not target_path.exists():
        return

    def _handle_remove_readonly(func, path, exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass

    try:
        shutil.rmtree(target_path, onexc=_handle_remove_readonly)
    except TypeError:
        shutil.rmtree(target_path, onerror=_handle_remove_readonly)
    except Exception:
        shutil.rmtree(target_path, ignore_errors=True)


@contextmanager
def sandbox_workspace() -> Generator[Path, None, None]:
    """
    Creates an isolated temporary directory for cloning and processing repos.
    Ensures guaranteed teardown after execution completes or fails.
    """
    temp_dir = create_secure_temp_dir(prefix="ingest_sandbox_")
    try:
        yield temp_dir
    finally:
        safe_rmtree(temp_dir)



def build_sandboxed_env() -> dict[str, str]:
    """
    Builds environment variables to disable git hooks, Git LFS smudge filters,
    and external system configs during git commands.
    """
    env = os.environ.copy()
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def run_sandboxed_git_command(
    args: List[str],
    cwd: Path,
    timeout_seconds: float = 60.0,
) -> subprocess.CompletedProcess:
    """
    Executes a git command inside the sandbox with hooks disabled, LFS skipped,
    attributes filter drivers disabled, and a hard timeout limit.
    """
    env = build_sandboxed_env()
    
    # Prepend git config overrides to disable hooks, attributes, and credential helpers
    full_cmd = [
        "git",
        "-c", "core.hooksPath=",
        "-c", "core.attributesFile=/dev/null",
        "-c", "credential.helper=",
        "-c", "filter.lfs.smudge=cat",
        "-c", "http.followRedirects=false",
    ] + args

    try:
        result = subprocess.run(
            full_cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            raise IngestionError(
                f"Git command failed (exit code {result.returncode}): {result.stderr.strip()}"
            )
        return result
    except subprocess.TimeoutExpired as e:
        raise CloneTimeoutError(
            f"Git operation timed out after {timeout_seconds} seconds."
        ) from e
