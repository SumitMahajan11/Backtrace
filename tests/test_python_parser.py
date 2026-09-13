"""Unit tests for Python AST structural parser (Layer 2 core)."""

import json
import pytest

from app.parser.python_parser import PythonLanguageParser
from app.parser.schema import ImportCategory, ParserResult


def test_python_static_and_wildcard_imports():
    code = """
import os
import sys
from datetime import datetime
from math import *
    """
    parser = PythonLanguageParser()
    all_files = {"app/main.py"}
    node, edges = parser.parse_single_file("app/main.py", code, all_files)

    assert node.path == "app/main.py"
    assert node.language == "python"

    categories = {edge.raw_import_symbol: edge.import_type for edge in edges}
    assert categories["os"] == "static"
    assert categories["sys"] == "static"
    assert categories["from datetime import datetime"] == "static"
    assert categories["from math import *"] == "star"


def test_python_dynamic_and_conditional_imports():
    code = """
import importlib

if TYPE_CHECKING:
    import typing_extensions

try:
    import optional_dep
except ImportError:
    pass

def load_plugin():
    mod = importlib.import_module("my_plugin")
    raw_mod = __import__("raw_plugin")
    """
    parser = PythonLanguageParser()
    all_files = {"app/main.py"}
    node, edges = parser.parse_single_file("app/main.py", code, all_files)

    dynamic_edges = [e for e in edges if e.import_type == "dynamic"]
    assert len(dynamic_edges) == 2
    assert all(not e.resolved for e in dynamic_edges)

    conditional_edges = [e for e in edges if e.import_type == "conditional"]
    assert len(conditional_edges) >= 2


def test_python_entry_point_and_symbols_extraction():
    code = """
class DataProcessor:
    def process(self):
        pass

def main():
    print("running")

if __name__ == "__main__":
    main()
    """
    parser = PythonLanguageParser()
    all_files = {"run.py"}
    node, edges = parser.parse_single_file("run.py", code, all_files)

    assert node.entry_point is True
    assert node.entry_point_type == "name_eq_main"
    assert "DataProcessor" in node.classes
    assert "main" in node.functions
    assert "DataProcessor" in node.exports
    assert "main" in node.exports


def test_python_internal_vs_external_import_resolution():
    code = """
import requests
import app.models.ingestion
    """
    parser = PythonLanguageParser()
    all_files = {"main.py", "app/models/ingestion.py"}
    node, edges = parser.parse_single_file("main.py", code, all_files)

    ext_edge = next(e for e in edges if e.target == "requests")
    assert ext_edge.is_external is True
    assert ext_edge.resolved is False

    int_edge = next(e for e in edges if e.target == "app/models/ingestion.py")
    assert int_edge.is_external is False
    assert int_edge.resolved is True


def test_python_syntax_error_handling():
    code = "def broken_syntax(:"
    parser = PythonLanguageParser()
    res = parser.parse_repository(["bad.py"], {"bad.py": code})

    assert len(res.parse_errors) == 1
    assert res.parse_errors[0].path == "bad.py"
    assert res.parse_errors[0].language == "python"


def test_json_round_trip_serialization():
    """Acceptance Criteria 5: Output schema survives a JSON round-trip."""
    code = """
import os
import requests
from .helper import run
    """
    parser = PythonLanguageParser()
    result = parser.parse_repository(["main.py"], {"main.py": code})

    # Serialize to JSON
    json_str = result.model_dump_json()
    assert isinstance(json_str, str)

    # Deserialize back from JSON
    deserialized = ParserResult.model_validate_json(json_str)

    assert deserialized.language == "python"
    assert deserialized.parser_version == "1.0.0"
    assert len(deserialized.files) == 1
    assert deserialized.files[0].path == "main.py"
