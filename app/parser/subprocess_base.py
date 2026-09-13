"""Abstract Base Class for Subprocess-based per-language static structural parsers."""

import json
import shutil
import subprocess
from abc import abstractmethod
from typing import Dict, List, Set, Tuple

from app.parser.base import BaseLanguageParser
from app.parser.schema import FileNode, ImportEdge


class SubprocessLanguageParser(BaseLanguageParser):
    """
    Abstract base class for language parsers that delegate AST parsing
    to an external helper binary/script via subprocess.
    
    Handles process execution, timeout enforcement, non-zero exits,
    missing binary checks, and malformed stdout JSON.
    """

    @property
    @abstractmethod
    def executable_cmd(self) -> List[str]:
        """Base command invocation list (e.g. ['node', 'scripts/parse_js.js'])."""
        pass

    @property
    def subprocess_timeout_seconds(self) -> float:
        """Default timeout for subprocess execution."""
        return 10.0

    def check_binary_available(self) -> bool:
        """Verifies if the executable tool is present on the system."""
        cmd = self.executable_cmd
        if not cmd:
            return False
        binary = cmd[0]
        return shutil.which(binary) is not None

    def execute_subprocess(self, file_path: str, code_content: str) -> Dict:
        """
        Executes the subprocess CLI safely passing JSON payload over stdin.
        Returns parsed JSON payload output from stdout.
        """
        cmd = self.executable_cmd
        if not cmd:
            raise ValueError(f"No executable command configured for {self.language_name} parser")

        payload = json.dumps({"file_path": file_path, "code_content": code_content})

        try:
            proc = subprocess.run(
                cmd,
                input=payload,
                capture_output=True,
                text=True,
                timeout=self.subprocess_timeout_seconds,
                check=True,
                shell=False,
            )
        except subprocess.TimeoutExpired as e:
            raise ValueError(f"{self.language_name} parse timeout after {self.subprocess_timeout_seconds}s: {e}") from e
        except subprocess.CalledProcessError as e:
            stderr_msg = e.stderr.strip() if e.stderr else str(e)
            raise ValueError(f"{self.language_name} helper process failed (exit code {e.returncode}): {stderr_msg}") from e
        except FileNotFoundError as e:
            raise ValueError(f"{self.language_name} helper binary not found: {cmd[0]}") from e
        except Exception as e:
            raise ValueError(f"{self.language_name} parse execution error: {e}") from e

        if not proc.stdout.strip():
            raise ValueError(f"{self.language_name} helper produced empty output")

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise ValueError(f"{self.language_name} helper emitted malformed JSON: {e}") from e

        if isinstance(data, dict) and data.get("error"):
            raise ValueError(f"{self.language_name} parse error: {data['error']}")

        return data
