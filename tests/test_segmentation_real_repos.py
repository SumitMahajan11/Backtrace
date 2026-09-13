"""Integration tests for Layer 4 SegmentationEngine against real-world repository paths."""

import pytest
from app.parser.python_parser import PythonLanguageParser
from app.parser.go_parser import GoLanguageParser
from app.segmentation.engine import SegmentationEngine
from app.segmentation.schema import ClassificationMethod, DomainType


def test_segmentation_on_flask_repo(tmp_path):
    # Simulate Flask repository files
    flask_files = {
        "src/flask/__init__.py": "from .app import Flask",
        "src/flask/app.py": "class Flask: pass",
        "src/flask/blueprints.py": "class Blueprint: pass",
        "src/flask/cli.py": "import click",
        "tests/test_basic.py": "def test_app(): pass",
        "docs/index.md": "# Flask Documentation",
        "pyproject.toml": "[build-system]",
    }

    parser = PythonLanguageParser()
    parse_result = parser.parse_repository(
        file_paths=list(flask_files.keys()),
        file_contents=flask_files,
    )

    engine = SegmentationEngine()
    seg_result = engine.segment_repository(
        file_nodes=parse_result.files,
        all_repo_files=list(flask_files.keys()),
    )

    assert seg_result.method_counts.get("convention", 0) >= 5
    assert seg_result.domain_counts.get("tests", 0) == 1
    assert seg_result.domain_counts.get("docs", 0) == 1
    assert seg_result.domain_counts.get("config", 0) == 1
    assert seg_result.domain_counts.get("core", 0) + seg_result.domain_counts.get("backend", 0) >= 3


def test_segmentation_on_gin_repo():
    # Simulate Gin repository files
    gin_files = {
        "gin.go": "package gin\nimport \"net/http\"",
        "context.go": "package gin\nimport \"fmt\"",
        "routergroup.go": "package gin",
        "context_test.go": "package gin\nimport \"testing\"",
        "go.mod": "module github.com/gin-gonic/gin",
        "README.md": "# Gin Web Framework",
    }

    parser = GoLanguageParser()
    parse_result = parser.parse_repository(
        file_paths=list(gin_files.keys()),
        file_contents=gin_files,
    )

    engine = SegmentationEngine()
    seg_result = engine.segment_repository(
        file_nodes=parse_result.files,
        all_repo_files=list(gin_files.keys()),
    )

    assert seg_result.domain_counts.get("core", 0) + seg_result.domain_counts.get("backend", 0) >= 3
    assert seg_result.domain_counts.get("tests", 0) == 1
    assert seg_result.domain_counts.get("config", 0) == 1
    assert seg_result.domain_counts.get("docs", 0) == 1
    assert seg_result.method_counts.get("convention", 0) >= 6
