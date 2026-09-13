"""Integration validation suite for Layer 6 (Stage A) against real-world repo dependency graphs (Flask, Gin)."""

import pytest
from app.parser.python_parser import PythonLanguageParser
from app.parser.go_parser import GoLanguageParser
from app.segmentation.engine import SegmentationEngine
from app.sequence.baseline_ordering import BaselineOrderingEngine


def test_baseline_ordering_on_flask_repo():
    """
    Validates BaselineOrderingEngine on a realistic Flask framework dependency structure.
    Files:
      - src/flask/config.py (depends on nothing internally)
      - src/flask/signals.py (depends on nothing internally)
      - src/flask/helpers.py (depends on signals.py)
      - src/flask/scaffold.py (depends on helpers.py)
      - src/flask/blueprints.py (depends on scaffold.py)
      - src/flask/app.py (depends on config.py, blueprints.py, helpers.py)
      - src/flask/__init__.py (depends on app.py)
      - tests/test_basic.py (isolated/unlinked in parser)
    """
    flask_files = {
        "src/flask/config.py": "class Config: pass",
        "src/flask/signals.py": "class Signal: pass",
        "src/flask/helpers.py": "from .signals import Signal",
        "src/flask/scaffold.py": "from .helpers import Signal",
        "src/flask/blueprints.py": "from .scaffold import Signal",
        "src/flask/app.py": "from .config import Config\nfrom .blueprints import Signal\nfrom .helpers import Signal",
        "src/flask/__init__.py": "from .app import Config",
        "tests/test_basic.py": "def test_app(): pass",
        "docs/index.md": "# Flask",
        "pyproject.toml": "[build-system]",
    }

    parser = PythonLanguageParser()
    parse_result = parser.parse_repository(
        file_paths=list(flask_files.keys()),
        file_contents=flask_files,
    )

    seg_engine = SegmentationEngine()
    seg_result = seg_engine.segment_repository(
        file_nodes=parse_result.files,
        all_repo_files=list(flask_files.keys()),
    )

    ordering_engine = BaselineOrderingEngine()
    order_result = ordering_engine.compute_baseline_order(
        file_nodes=parse_result.files,
        segmentation_result=seg_result,
        all_repo_files=list(flask_files.keys()),
    )

    # 1. Verify isolated files (docs, test, pyproject.toml have no internal import links)
    assert "docs/index.md" in order_result.isolated_files
    assert "pyproject.toml" in order_result.isolated_files
    assert "tests/test_basic.py" in order_result.isolated_files

    # 2. Spot-check intuition: config.py and signals.py have no prerequisites -> Tier 0
    tier_0 = order_result.tiers[0].files
    assert "src/flask/config.py" in tier_0
    assert "src/flask/signals.py" in tier_0

    # Find tier index for each file
    file_to_tier = {}
    for tier in order_result.tiers:
        for f in tier.files:
            file_to_tier[f] = tier.tier_index

    # 3. Spot-check dependency ordering chain:
    # config.py (Tier 0) < app.py
    # signals.py < helpers.py < scaffold.py < blueprints.py < app.py < __init__.py
    assert file_to_tier["src/flask/signals.py"] < file_to_tier["src/flask/helpers.py"]
    assert file_to_tier["src/flask/helpers.py"] < file_to_tier["src/flask/scaffold.py"]
    assert file_to_tier["src/flask/scaffold.py"] < file_to_tier["src/flask/blueprints.py"]
    assert file_to_tier["src/flask/blueprints.py"] < file_to_tier["src/flask/app.py"]
    assert file_to_tier["src/flask/app.py"] < file_to_tier["src/flask/__init__.py"]


def test_baseline_ordering_on_gin_repo():
    """
    Validates BaselineOrderingEngine on a realistic Gin web framework dependency structure.
    Files:
      - mode.go (config/mode settings, depends on stdlib only)
      - context.go (depends on mode.go)
      - routergroup.go (depends on context.go)
      - gin.go (depends on routergroup.go, context.go, mode.go)
      - README.md (isolated)
    """
    gin_files = {
        "mode.go": "package gin\nimport \"fmt\"",
        "context.go": "package gin\nimport \"example.com/gin/mode\"",
        "routergroup.go": "package gin\nimport \"example.com/gin/context\"",
        "gin.go": "package gin\nimport (\n\t\"example.com/gin/mode\"\n\t\"example.com/gin/context\"\n\t\"example.com/gin/routergroup\"\n)",
        "go.mod": "module example.com/gin\n\ngo 1.22",
        "README.md": "# Gin Web Framework",
    }

    parser = GoLanguageParser()
    parse_result = parser.parse_repository(
        file_paths=list(gin_files.keys()),
        file_contents=gin_files,
    )

    seg_engine = SegmentationEngine()
    seg_result = seg_engine.segment_repository(
        file_nodes=parse_result.files,
        all_repo_files=list(gin_files.keys()),
    )

    ordering_engine = BaselineOrderingEngine()
    order_result = ordering_engine.compute_baseline_order(
        file_nodes=parse_result.files,
        segmentation_result=seg_result,
        all_repo_files=list(gin_files.keys()),
    )

    # 1. Verify isolated non-code files
    assert "README.md" in order_result.isolated_files
    assert "go.mod" in order_result.isolated_files

    # 2. Spot-check intuition: mode.go has 0 internal dependencies -> Tier 0
    file_to_tier = {}
    for tier in order_result.tiers:
        for f in tier.files:
            file_to_tier[f] = tier.tier_index

    assert file_to_tier["mode.go"] == 0
    assert file_to_tier["mode.go"] < file_to_tier["context.go"]
    assert file_to_tier["context.go"] < file_to_tier["routergroup.go"]
    assert file_to_tier["routergroup.go"] < file_to_tier["gin.go"]
