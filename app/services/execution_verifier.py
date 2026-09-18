"""Execution Verification Engine utilizing self-hosted Piston isolated code execution."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional
import httpx


class ExecutionVerifierError(Exception):
    """Base exception for execution verification errors."""
    pass


class ExecutionVerifierConnectionError(ExecutionVerifierError):
    """Raised when the Piston execution engine is unreachable."""
    pass


class ExecutionVerifier:
    """
    Execution Verification service that dispatches code to a self-hosted Piston engine
    running in an isolated network sandbox.
    """

    # Maximum characters of stdout/stderr retained to prevent DB storage exhaustion
    MAX_OUTPUT_CHARS: int = 65536
    # Default execution timeout in milliseconds (Piston native limit)
    DEFAULT_RUN_TIMEOUT_MS: int = 3000
    # Default compilation timeout in milliseconds
    DEFAULT_COMPILE_TIMEOUT_MS: int = 10000
    # Default memory limit in bytes (128MB)
    DEFAULT_MEMORY_LIMIT_BYTES: int = 134217728

    LANGUAGE_ALIASES: Dict[str, str] = {
        "python": "python",
        "py": "python",
        "python3": "python",
        "javascript": "javascript",
        "js": "javascript",
        "node": "javascript",
        "typescript": "typescript",
        "ts": "typescript",
        "bash": "bash",
        "sh": "bash",
        "shell": "bash",
        "go": "go",
        "golang": "go",
        "rust": "rust",
        "rs": "rust",
        "c": "c",
        "cpp": "cpp",
        "c++": "cpp",
        "java": "java",
    }

    FILE_EXTENSIONS: Dict[str, str] = {
        "python": "solution.py",
        "javascript": "solution.js",
        "typescript": "solution.ts",
        "bash": "solution.sh",
        "go": "solution.go",
        "rust": "solution.rs",
        "c": "solution.c",
        "cpp": "solution.cpp",
        "java": "Solution.java",
    }

    def __init__(
        self,
        piston_url: Optional[str] = None,
        max_output_chars: int = MAX_OUTPUT_CHARS,
        default_timeout_ms: int = DEFAULT_RUN_TIMEOUT_MS,
        default_compile_timeout_ms: int = DEFAULT_COMPILE_TIMEOUT_MS,
        default_memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    ) -> None:
        from app.services.piston_health import piston_health_monitor
        base_url = (piston_url or os.getenv("PISTON_URL", "http://127.0.0.1:2000")).rstrip("/")
        if piston_health_monitor.piston_url:
            base_url = piston_health_monitor.piston_url
        self.piston_url = base_url
        self.max_output_chars = max_output_chars
        self.default_timeout_ms = default_timeout_ms
        self.default_compile_timeout_ms = default_compile_timeout_ms
        self.default_memory_limit_bytes = default_memory_limit_bytes

    def normalize_language(self, language: str) -> str:
        """Normalizes user/runtime language strings to standard Piston runtime keys."""
        lang_clean = (language or "python").strip().lower()
        return self.LANGUAGE_ALIASES.get(lang_clean, lang_clean)

    def _get_filename_for_language(self, language: str) -> str:
        """Returns standard filename suitable for language compilation/execution."""
        norm = self.normalize_language(language)
        return self.FILE_EXTENSIONS.get(norm, f"solution.{norm}")

    def _truncate_output(self, text: Optional[str]) -> tuple[str, bool]:
        """Truncates output string if exceeding maximum allowed characters."""
        if not text:
            return "", False
        if len(text) > self.max_output_chars:
            truncated_text = (
                text[: self.max_output_chars]
                + f"\n\n[Output truncated: exceeded {self.max_output_chars} characters limit]"
            )
            return truncated_text, True
        return text, False

    def get_runtimes(self) -> List[Dict[str, Any]]:
        """Queries Piston engine for available installed runtimes and packages."""
        url = f"{self.piston_url}/api/v2/runtimes"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            raise ExecutionVerifierConnectionError(
                f"Failed to connect to Piston engine at {url}: {exc}"
            ) from exc

    def execute(
        self,
        submitted_code: str,
        language: str = "python",
        version: Optional[str] = None,
        run_timeout_ms: Optional[int] = None,
        compile_timeout_ms: Optional[int] = None,
        run_memory_limit_bytes: Optional[int] = None,
        stdin: str = "",
        args: Optional[List[str]] = None,
        files: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Executes submitted code against Piston sandbox and returns real stdout, stderr,
        exit code, and execution time.
        """
        norm_language = self.normalize_language(language)
        run_timeout = run_timeout_ms if run_timeout_ms is not None else self.default_timeout_ms
        run_timeout = min(max(100, run_timeout), 3000)
        compile_timeout = compile_timeout_ms if compile_timeout_ms is not None else self.default_compile_timeout_ms
        memory_limit = run_memory_limit_bytes if run_memory_limit_bytes is not None else self.default_memory_limit_bytes

        if not files:
            filename = self._get_filename_for_language(norm_language)
            files_payload = [{"name": filename, "content": submitted_code}]
        else:
            files_payload = files

        payload: Dict[str, Any] = {
            "language": norm_language,
            "version": version or "*",
            "files": files_payload,
            "stdin": stdin or "",
            "args": args or [],
            "run_timeout": run_timeout,
            "compile_timeout": compile_timeout,
            "run_memory_limit": memory_limit,
        }

        from app.services.piston_health import piston_health_monitor

        # Fast-fail gate: If Piston is marked unhealthy, fail immediately without waiting for timeouts
        if not piston_health_monitor.is_healthy:
            raise ExecutionVerifierConnectionError(
                "Code execution is temporarily unavailable, try again shortly"
            )

        effective_url = self.piston_url
        if piston_health_monitor.piston_url and piston_health_monitor.piston_url != self.piston_url:
            effective_url = piston_health_monitor.piston_url

        url = f"{effective_url}/api/v2/execute"
        # Client HTTP timeout should be slightly higher than Piston's run + compile timeout
        client_timeout_sec = ((run_timeout + compile_timeout) / 1000.0) + 5.0

        start_time = time.perf_counter()
        try:
            with httpx.Client(timeout=client_timeout_sec) as client:
                response = client.post(url, json=payload)
                elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Try syncing health monitor to discover dynamic WSL host IP
            piston_health_monitor.check_health_sync()
            if piston_health_monitor.is_healthy and piston_health_monitor.piston_url != effective_url:
                try:
                    retry_url = f"{piston_health_monitor.piston_url}/api/v2/execute"
                    with httpx.Client(timeout=client_timeout_sec) as client:
                        response = client.post(retry_url, json=payload)
                        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
                        self.piston_url = piston_health_monitor.piston_url
                except Exception:
                    raise ExecutionVerifierConnectionError(
                        "Code execution is temporarily unavailable, try again shortly"
                    ) from exc
            else:
                raise ExecutionVerifierConnectionError(
                    "Code execution is temporarily unavailable, try again shortly"
                ) from exc
        except httpx.TimeoutException as exc:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return {
                "language": norm_language,
                "version": version or "*",
                "stdout": "",
                "stderr": f"Execution timed out on engine client ({elapsed_ms}ms)",
                "exit_code": -1,
                "signal": "SIGKILL",
                "execution_time_ms": elapsed_ms,
                "status": "timeout",
                "truncated": False,
                "raw_response": None,
            }
        except Exception as exc:
            raise ExecutionVerifierError(f"Execution verification request failed: {exc}") from exc

        if response.status_code != 200:
            err_body = response.text
            return {
                "language": norm_language,
                "version": version or "*",
                "stdout": "",
                "stderr": f"Piston engine error (HTTP {response.status_code}): {err_body}",
                "exit_code": -1,
                "signal": None,
                "execution_time_ms": elapsed_ms,
                "status": "error",
                "truncated": False,
                "raw_response": None,
            }

        res_json = response.json()
        compile_stage = res_json.get("compile")
        run_stage = res_json.get("run") or {}

        # If compilation failed, return compile stderr
        if compile_stage and compile_stage.get("code") != 0 and compile_stage.get("code") is not None:
            raw_stderr = compile_stage.get("stderr") or compile_stage.get("output", "")
            raw_stdout = compile_stage.get("stdout", "")
            exit_code = compile_stage.get("code")
            signal = compile_stage.get("signal")
        else:
            raw_stdout = run_stage.get("stdout", "")
            raw_stderr = run_stage.get("stderr", "")
            run_message = run_stage.get("message")
            if run_message and run_message not in raw_stderr:
                raw_stderr = f"{raw_stderr}\n[Sandbox Notice: {run_message}]".strip()
            exit_code = run_stage.get("code")
            signal = run_stage.get("signal")

        stdout_trunc, trunc_out = self._truncate_output(raw_stdout)
        stderr_trunc, trunc_err = self._truncate_output(raw_stderr)
        
        run_msg_lower = (run_stage.get("message") or "").lower()
        if "stdout length exceeded" in run_msg_lower or "output length exceeded" in run_msg_lower:
            trunc_out = True

        is_truncated = trunc_out or trunc_err

        # Detect timeout vs output cap vs normal execution
        is_output_cap = "stdout length exceeded" in run_msg_lower or "output length exceeded" in run_msg_lower
        is_timeout = (
            not is_output_cap
            and (
                signal in ("SIGKILL", "SIGTERM", "SIGXCPU")
                or "timed out" in (stderr_trunc or "").lower()
                or "timed out" in (stdout_trunc or "").lower()
                or "time limit exceeded" in run_msg_lower
            )
        )

        status_str = "timeout" if is_timeout else ("success" if exit_code == 0 and not is_output_cap else "error")

        return {
            "language": res_json.get("language", norm_language),
            "version": res_json.get("version", version or "*"),
            "stdout": stdout_trunc,
            "stderr": stderr_trunc,
            "exit_code": exit_code,
            "signal": signal,
            "execution_time_ms": elapsed_ms,
            "status": status_str,
            "truncated": is_truncated,
            "raw_response": res_json,
        }
