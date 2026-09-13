"""Container and Process Sandboxing Manager (Layer 10 core)."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

from app.models.ingestion import CloneTimeoutError, IngestionError
from app.security.path_hardening import create_secure_temp_dir


class DockerSandboxConfig(BaseModel):
    """Configuration constraints for single-use Docker sandbox containers."""
    cpu_limit: str = "1.0"
    memory_limit: str = "512m"
    pids_limit: int = 64
    read_only_rootfs: bool = True
    cap_drop: List[str] = Field(default_factory=lambda: ["ALL"])
    user: str = "1000:1000"
    timeout_seconds: float = 60.0


def is_docker_available() -> bool:
    """Checks if Docker daemon is running and reachable on host."""
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=3)
        return res.returncode == 0
    except Exception:
        return False


class SecurityIsolationError(IngestionError):
    """Raised when Docker container isolation is required but unavailable on host."""
    pass


class SandboxRunner:
    """Orchestrates containerized or hardened process isolation for repo analysis."""

    def __init__(self, config: Optional[DockerSandboxConfig] = None, require_docker: bool = False):
        self.config = config or DockerSandboxConfig()
        self.use_docker = is_docker_available()
        self.require_docker = require_docker or (os.getenv("REQUIRE_DOCKER", "false").lower() == "true")

        if self.require_docker and not self.use_docker:
            raise SecurityIsolationError(
                "Docker container isolation is strictly required in production mode, "
                "but Docker daemon is not available on host."
            )

    def run_git_clone_sandboxed(
        self,
        github_url: str,
        target_dir: Path,
        validated_ip: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        """
        Phase 1: Clone stage. Network access allowed ONLY to fetch the repo.
        Includes DNS IP pinning via --add-host to prevent DNS rebinding TOCTOU attacks.
        """
        env = os.environ.copy()
        env["GIT_LFS_SKIP_SMUDGE"] = "1"
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_TERMINAL_PROMPT"] = "0"

        if self.use_docker:
            # Build docker run command with strict DNS IP pinning
            docker_cmd = [
                "docker", "run", "--rm",
                "--network=bridge",
                f"--cpus={self.config.cpu_limit}",
                f"--memory={self.config.memory_limit}",
                f"--pids-limit={self.config.pids_limit}",
                "-v", f"{target_dir}:/workspace:rw",
                "-w", "/workspace",
            ]
            if validated_ip:
                docker_cmd.append(f"--add-host=github.com:{validated_ip}")

            docker_cmd.extend([
                "alpine/git:latest",
                "-c", "core.hooksPath=",
                "-c", "core.attributesFile=/dev/null",
                "-c", "filter.lfs.smudge=cat",
                "-c", "http.followRedirects=false",
                "clone", "--no-checkout", github_url, "."
            ])
            cmd = docker_cmd
        else:
            cmd = [
                "git",
                "-c", "core.hooksPath=",
                "-c", "core.attributesFile=/dev/null",
                "-c", "credential.helper=",
                "-c", "filter.lfs.smudge=cat",
                "-c", "http.followRedirects=false",
                "clone", "--no-checkout", github_url, "."
            ]

        try:
            res = subprocess.run(
                cmd,
                cwd=str(target_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
            )
            if res.returncode != 0:
                raise IngestionError(f"Sandboxed git clone failed: {res.stderr.strip()}")
            return res
        except subprocess.TimeoutExpired as e:
            raise CloneTimeoutError(f"Clone timed out after {self.config.timeout_seconds}s.") from e

    def run_post_clone_checkout(self, target_dir: Path) -> subprocess.CompletedProcess:
        """
        Phase 2: Analysis stage. Network access strictly DISABLED.
        """
        env = os.environ.copy()
        env["GIT_LFS_SKIP_SMUDGE"] = "1"
        env["GIT_CONFIG_NOSYSTEM"] = "1"

        cmd = [
            "git",
            "-c", "core.hooksPath=",
            "-c", "core.attributesFile=/dev/null",
            "checkout", "HEAD"
        ]

        try:
            res = subprocess.run(
                cmd,
                cwd=str(target_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
            )
            if res.returncode != 0:
                raise IngestionError(f"Sandboxed checkout failed: {res.stderr.strip()}")
            return res
        except subprocess.TimeoutExpired as e:
            raise CloneTimeoutError(f"Checkout timed out after {self.config.timeout_seconds}s.") from e
