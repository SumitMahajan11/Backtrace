"""Integration tests for Layer 11 Pipeline Orchestrator."""

import pytest
from pathlib import Path
from app.orchestration.pipeline import PipelineOrchestrator
from app.orchestration.schema import PipelineStage, PipelineProgressEvent


def test_pipeline_orchestrator_synthetic_repo():
    files = {
        "src/config.py": "class Config:\n    ENV = 'dev'\n",
        "src/service.py": "from .config import Config\nclass Service:\n    pass\n",
        "src/app.py": "from .service import Service\ndef main():\n    pass\n",
        "tests/test_app.py": "from src.app import main\ndef test_main():\n    pass\n",
    }
    file_paths = list(files.keys())

    orchestrator = PipelineOrchestrator()
    res = orchestrator.run_pipeline(
        repo_name="synthetic-service",
        file_paths=file_paths,
        file_contents=files,
        enable_rag=True,
    )

    assert res.success is True
    assert res.repo_name == "synthetic-service"
    assert res.report is not None
    assert res.report.architecture_overview.total_files == 4
    assert res.report.total_milestones >= 3
    assert len(res.markdown_output) > 200
    assert "graph_output" in res.model_dump()
    assert res.quiz_output["total_questions"] >= 2


def test_pipeline_orchestrator_progress_callback_events():
    files = {
        "main.go": "package main\nfunc main() {}\n",
    }
    file_paths = list(files.keys())

    received_events = []
    def on_progress(ev: PipelineProgressEvent):
        received_events.append(ev)

    orchestrator = PipelineOrchestrator()
    res = orchestrator.run_pipeline(
        repo_name="go-micro",
        file_paths=file_paths,
        file_contents=files,
        progress_callback=on_progress,
        enable_rag=False,
    )

    assert res.success is True
    assert len(received_events) >= 5
    stages_seen = [ev.stage for ev in received_events]
    assert PipelineStage.INGESTION in stages_seen
    assert PipelineStage.PARSING in stages_seen
    assert PipelineStage.UNDERSTANDING in stages_seen
    assert PipelineStage.SEQUENCE_REASONING in stages_seen
    assert PipelineStage.SYNTHESIS in stages_seen
    assert PipelineStage.COMPLETE in stages_seen


def test_pipeline_orchestrator_on_flask_repo_fixture():
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

    orchestrator = PipelineOrchestrator()
    res = orchestrator.run_pipeline(
        repo_name="pallets/flask-sample",
        file_paths=list(flask_files.keys()),
        file_contents=flask_files,
        enable_rag=True,
    )

    assert res.success is True
    assert res.report is not None
    assert res.report.architecture_overview.primary_language == "python"
    assert res.report.total_milestones >= 4
    assert "src/flask/config.py" in res.report.milestones[0].files
