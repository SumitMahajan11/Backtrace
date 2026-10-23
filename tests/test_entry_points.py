"""Tests for application entry point detection and test file exclusions."""

import os
from pathlib import Path
import pytest

from app.parser.python_parser import PythonLanguageParser


def test_fastapi_layout_entry_points():
    """Verify entry points in tests/fixtures/fastapi_layout/ yield ['main.py'] and exclude test_main.py."""
    fixture_dir = Path(__file__).parent / "fixtures" / "fastapi_layout"
    parser = PythonLanguageParser()

    file_paths = [
        "main.py",
        "app/routes.py",
        "tests/test_main.py",
    ]
    all_repo_files = set(file_paths)

    nodes = []
    entry_points = []
    for rel_path in file_paths:
        full_path = fixture_dir / rel_path
        with open(full_path, "r", encoding="utf-8") as f:
            code = f.read()
        node, _ = parser.parse_single_file(rel_path, code, all_repo_files)
        nodes.append(node)
        if node.entry_point:
            entry_points.append(node.path)

    # Assertions required by Part A
    assert sorted(entry_points) == ["main.py"]
    assert "tests/test_main.py" not in entry_points

    # Verify per-file node properties
    main_node = next(n for n in nodes if n.path == "main.py")
    assert main_node.entry_point is True

    routes_node = next(n for n in nodes if n.path == "app/routes.py")
    assert routes_node.entry_point is False

    test_node = next(n for n in nodes if n.path == "tests/test_main.py")
    assert test_node.entry_point is False


def test_entry_point_detection_rules():
    """Test all application entry point detection rules."""
    parser = PythonLanguageParser()
    all_files = {"app.py", "server.py", "manage.py", "wsgi.py", "asgi.py", "worker.py", "deep/nested/pkg/worker.py"}

    # Rule 1: FastAPI, Flask, Django
    n1, _ = parser.parse_single_file("worker.py", "from fastapi import FastAPI\napp = FastAPI()", all_files)
    assert n1.entry_point is True

    n2, _ = parser.parse_single_file("worker.py", "from flask import Flask\napp = Flask(__name__)", all_files)
    assert n2.entry_point is True

    n3, _ = parser.parse_single_file("worker.py", "WSGI_APPLICATION = 'myproject.wsgi.application'", all_files)
    assert n3.entry_point is True

    # Rule 2: if __name__ == "__main__"
    n4, _ = parser.parse_single_file("worker.py", "if __name__ == '__main__':\n    pass", all_files)
    assert n4.entry_point is True

    # Rule 3: named main.py, app.py, manage.py, wsgi.py, asgi.py, server.py at root or top-level package
    n5, _ = parser.parse_single_file("manage.py", "# empty manage", all_files)
    assert n5.entry_point is True

    n6, _ = parser.parse_single_file("server.py", "# empty server", all_files)
    assert n6.entry_point is True

    # Rule 4: contains uvicorn.run(
    n7, _ = parser.parse_single_file("worker.py", "import uvicorn\nuvicorn.run(app)", all_files)
    assert n7.entry_point is True

    # Nested worker should not match rule 3
    n8, _ = parser.parse_single_file("deep/nested/pkg/worker.py", "# ordinary module", all_files)
    assert n8.entry_point is False


def test_test_file_exclusion_rules():
    """Verify test files matching tests/, test_*.py, *_test.py, conftest.py are excluded."""
    parser = PythonLanguageParser()
    all_files = {"tests/suite.py", "test_core.py", "service_test.py", "conftest.py"}

    code_with_main = "if __name__ == '__main__':\n    run_tests()"
    code_with_fastapi = "from fastapi import FastAPI\napp = FastAPI()"

    # Any test path must be excluded even if containing entry point constructs
    for test_path in ["tests/runner.py", "src/tests/runner.py", "test_views.py", "integration_test.py", "conftest.py"]:
        node, _ = parser.parse_single_file(test_path, code_with_main, {test_path})
        assert node.entry_point is False, f"Expected {test_path} to be excluded from entry points"

        node_api, _ = parser.parse_single_file(test_path, code_with_fastapi, {test_path})
        assert node_api.entry_point is False, f"Expected {test_path} with FastAPI to be excluded"
