"""Unit tests for SubprocessLanguageParser base class failure modes (PROMPT_2F Part A)."""

import pytest
from typing import List, Set, Tuple
from unittest.mock import MagicMock, patch
import subprocess

from app.parser.subprocess_base import SubprocessLanguageParser
from app.parser.schema import FileNode, ImportEdge


class DummySubprocessParser(SubprocessLanguageParser):
    """Dummy subclass of SubprocessLanguageParser for failure mode testing."""

    @property
    def language_name(self) -> str:
        return "dummy"

    @property
    def file_extensions(self) -> Set[str]:
        return {".dummy"}

    @property
    def executable_cmd(self) -> List[str]:
        return ["dummy_cmd"]

    def parse_single_file(
        self, file_path: str, code_content: str, all_repo_files: Set[str]
    ) -> Tuple[FileNode, List[ImportEdge]]:
        data = self.execute_subprocess(file_path, code_content)
        return FileNode(path=file_path, language=self.language_name), []


def test_subprocess_timeout_failure():
    parser = DummySubprocessParser()
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["dummy_cmd"], 10.0)):
        with pytest.raises(ValueError, match="dummy parse timeout after 10.0s"):
            parser.execute_subprocess("test.dummy", "content")


def test_subprocess_non_zero_exit_failure():
    parser = DummySubprocessParser()
    err = subprocess.CalledProcessError(1, ["dummy_cmd"], stderr="Fatal parser crash")
    with patch("subprocess.run", side_effect=err):
        with pytest.raises(ValueError, match="dummy helper process failed \\(exit code 1\\): Fatal parser crash"):
            parser.execute_subprocess("test.dummy", "content")


def test_subprocess_malformed_json_failure():
    parser = DummySubprocessParser()
    mock_proc = MagicMock()
    mock_proc.stdout = "THIS IS NOT JSON {{{"
    with patch("subprocess.run", return_value=mock_proc):
        with pytest.raises(ValueError, match="dummy helper emitted malformed JSON"):
            parser.execute_subprocess("test.dummy", "content")


def test_subprocess_missing_binary_failure():
    parser = DummySubprocessParser()
    with patch("subprocess.run", side_effect=FileNotFoundError("No such binary")):
        with pytest.raises(ValueError, match="dummy helper binary not found: dummy_cmd"):
            parser.execute_subprocess("test.dummy", "content")


def test_subprocess_binary_available_check():
    parser = DummySubprocessParser()
    with patch("shutil.which", return_value=None):
        assert parser.check_binary_available() is False

    with patch("shutil.which", return_value="/usr/bin/dummy_cmd"):
        assert parser.check_binary_available() is True


def test_subprocess_batch_resilience_produces_parse_errors():
    """Confirms non-zero exit / malformed JSON helper failures produce ParseError entries without crashing the batch."""
    parser = DummySubprocessParser()

    def mock_run(cmd, input, capture_output, text, timeout, check, shell):
        payload = input
        if "bad_crash.dummy" in payload:
            raise subprocess.CalledProcessError(1, cmd, stderr="Process crashed")
        elif "bad_json.dummy" in payload:
            m = MagicMock()
            m.stdout = "MALFORMED"
            return m
        else:
            m = MagicMock()
            m.stdout = '{"ok": true}'
            return m

    file_paths = ["good1.dummy", "bad_crash.dummy", "good2.dummy", "bad_json.dummy"]
    file_contents = {p: f"code for {p}" for p in file_paths}

    with patch("subprocess.run", side_effect=mock_run):
        result = parser.parse_repository(file_paths, file_contents)

    # 2 good files parsed into file_nodes
    assert len(result.files) == 2
    parsed_paths = {f.path for f in result.files}
    assert parsed_paths == {"good1.dummy", "good2.dummy"}

    # 2 bad files captured as ParseError entries in parse_errors
    assert len(result.parse_errors) == 2
    error_paths = {e.path for e in result.parse_errors}
    assert error_paths == {"bad_crash.dummy", "bad_json.dummy"}
    for err in result.parse_errors:
        assert err.language == "dummy"
        assert len(err.error_message) > 0
