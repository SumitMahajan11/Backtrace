"""Unit and threat model tests for Structural Verification Engine (Prompt 11)."""

import pytest
from app.services.structural_verifier import (
    StructuralVerifier,
    StructuralVerificationError,
    SymbolDefinition,
)
from app.utils.file_filter import MAX_FILE_SIZE_BYTES


@pytest.fixture
def verifier():
    return StructuralVerifier()


def test_symbol_definition_matching():
    """Test SymbolDefinition matching with kind and arg count."""
    sym_func = SymbolDefinition(name="process_data", kind="function", arg_count=2, args=["data", "config"])
    sym_func_match = SymbolDefinition(name="process_data", kind="function", arg_count=2, args=["data", "config"])
    sym_func_diff_args = SymbolDefinition(name="process_data", kind="function", arg_count=1, args=["data"])
    sym_class = SymbolDefinition(name="process_data", kind="class")

    assert sym_func.matches(sym_func_match) is True
    assert sym_func.matches(sym_func_diff_args) is False
    assert sym_func.matches(sym_class) is False


def test_verifier_full_match(verifier):
    """Test (a) code that fully matches expected symbol table."""
    code = """
class Config:
    def __init__(self, path: str):
        self.path = path

    def validate(self) -> bool:
        return True

def load_config(path: str) -> Config:
    return Config(path)
"""
    expected = [
        {"name": "Config", "kind": "class"},
        {"name": "load_config", "kind": "function", "arg_count": 1},
        {"name": "validate", "kind": "function", "arg_count": 1},
    ]

    res = verifier.verify(code, expected, language="python")

    assert res["structurally_verified"] is True
    assert res["syntax_valid"] is True
    assert res["error_message"] is None
    assert len(res["missing_symbols"]) == 0
    assert len(res["present_symbols"]) == 3
    assert any(s["matched"]["name"] == "Config" for s in res["present_symbols"])
    assert any(s["matched"]["name"] == "load_config" for s in res["present_symbols"])
    assert any(s["matched"]["name"] == "validate" for s in res["present_symbols"])


def test_verifier_missing_one_symbol(verifier):
    """Test (b) code missing one required symbol."""
    code = """
class Config:
    def __init__(self, path: str):
        self.path = path

    def validate(self) -> bool:
        return True
"""
    expected = [
        {"name": "Config", "kind": "class"},
        {"name": "load_config", "kind": "function", "arg_count": 1},
        {"name": "validate", "kind": "function", "arg_count": 1},
    ]

    res = verifier.verify(code, expected, language="python")

    assert res["structurally_verified"] is False
    assert res["syntax_valid"] is True
    assert len(res["missing_symbols"]) == 1
    assert res["missing_symbols"][0]["name"] == "load_config"
    assert len(res["present_symbols"]) == 2


def test_verifier_extra_symbol(verifier):
    """Test (c) code with an extra unrelated symbol."""
    code = """
class Config:
    def __init__(self, path: str):
        self.path = path

    def validate(self) -> bool:
        return True

def load_config(path: str) -> Config:
    return Config(path)

def extra_debug_helper(msg: str) -> None:
    print(msg)
"""
    expected = [
        {"name": "Config", "kind": "class"},
        {"name": "load_config", "kind": "function", "arg_count": 1},
        {"name": "validate", "kind": "function", "arg_count": 1},
    ]

    res = verifier.verify(code, expected, language="python")

    # Extra symbols are informational, not a verification failure
    assert res["structurally_verified"] is True
    assert res["syntax_valid"] is True
    assert len(res["missing_symbols"]) == 0
    assert len(res["present_symbols"]) == 3
    assert len(res["extra_symbols"]) >= 1
    assert any(s["name"] == "extra_debug_helper" for s in res["extra_symbols"])


def test_verifier_syntax_error_handled_gracefully(verifier):
    """Test that adversarial syntax errors do not crash the verifier."""
    code = "def broken_func(:\n    pass !!!"
    expected = [{"name": "broken_func", "kind": "function"}]

    res = verifier.verify(code, expected, language="python")

    assert res["structurally_verified"] is False
    assert res["syntax_valid"] is False
    assert res["error_message"] is not None
    assert "SyntaxError" in res["error_message"]
    assert len(res["missing_symbols"]) == 1


def test_verifier_dos_size_limit(verifier):
    """Test Threat Model: submissions exceeding 1MB are rejected."""
    oversized_code = "# " + ("A" * (MAX_FILE_SIZE_BYTES + 1024))
    expected = [{"name": "foo", "kind": "function"}]

    with pytest.raises(StructuralVerificationError) as exc_info:
        verifier.verify(oversized_code, expected, language="python")

    assert "exceeds maximum limit" in str(exc_info.value)


def test_verifier_never_executes_code(verifier, tmp_path):
    """Test Threat Model: malicious code is strictly parsed, never executed."""
    canary_file = tmp_path / "canary.txt"
    malicious_code = f"""
import os
os.system("echo PWNED > {canary_file.as_posix()}")

def target_func():
    return "safe"
"""
    expected = [{"name": "target_func", "kind": "function"}]

    res = verifier.verify(malicious_code, expected, language="python")

    # The canary file must NOT have been created because code is never executed
    assert not canary_file.exists()
    assert res["structurally_verified"] is True
    assert any(s["matched"]["name"] == "target_func" for s in res["present_symbols"])


def test_verifier_rejects_stub_function_bodies(verifier):
    """Test that functions with only pass, ..., docstring, or raise NotImplementedError fail verification."""
    stub_cases = [
        ("pass", "def calculate():\n    pass"),
        ("ellipsis", "def calculate():\n    ..."),
        ("docstring", 'def calculate():\n    """Only a docstring description."""'),
        ("raise_bare", "def calculate():\n    raise NotImplementedError"),
        ("raise_call", 'def calculate():\n    raise NotImplementedError("TODO")'),
        ("doc_and_pass", 'def calculate():\n    """Docstring"""\n    pass'),
        ("doc_and_ellipsis", 'def calculate():\n    """Docstring"""\n    ...'),
    ]
    expected = [{"name": "calculate", "kind": "function"}]

    for name, code in stub_cases:
        res = verifier.verify(code, expected, language="python")
        assert res["structurally_verified"] is False, f"Case {name} should have failed verification"
        assert len(res["stub_symbols"]) == 1, f"Case {name} should have 1 stub symbol"
        assert res["stub_symbols"][0]["expected"]["name"] == "calculate"
        assert "unimplemented placeholder stub" in res["error_message"]


def test_verifier_accepts_valid_bodies(verifier):
    """Test that real implementations (even returning False or simple expressions) pass verification."""
    valid_cases = [
        ("return_false", "def calculate():\n    return False"),
        ("return_true", "def calculate():\n    return True"),
        ("assign_and_return", "def calculate():\n    x = 10\n    return x * 2"),
    ]
    expected = [{"name": "calculate", "kind": "function"}]

    for name, code in valid_cases:
        res = verifier.verify(code, expected, language="python")
        assert res["structurally_verified"] is True, f"Case {name} should pass verification"
        assert len(res["stub_symbols"]) == 0
        assert len(res["present_symbols"]) == 1

