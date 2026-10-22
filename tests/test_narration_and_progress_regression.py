"""Regression test suite for narration engine, LLM provider selection,
source propagation, and progress SSE event reliability.
"""

import json
import os
import time
from unittest.mock import MagicMock, patch
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.core.config import get_settings
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, UserModel
from app.orchestration.pipeline import PipelineOrchestrator
from app.orchestration.schema import PipelineResult, PipelineStage
from app.security.auth import create_access_token
from app.sequence.llm_client import create_ollama_provider, get_default_llm_provider
from app.sequence.narration_engine import NarrationEngine
from app.sequence.schema import (
    RepoConfidenceSummary,
    ScoredFileEntry,
    ScoredOrderingResult,
)
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.user_repository import UserRepository


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    yield TestingSessionLocal, engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_db):
    TestingSessionLocal, _ = test_db

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(test_db) -> UserModel:
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        user = UserRepository.upsert_github_user(
            session=session,
            github_id=888001,
            github_username="regression_tester",
            email="regression@example.com",
            avatar_url="https://avatars.example.com/tester",
        )
        session.commit()
        session.refresh(user)
        return user


@pytest.fixture
def sample_scored() -> ScoredOrderingResult:
    files = [
        ScoredFileEntry(
            path="src/config.py",
            tier_index=0,
            confidence="high",
            confidence_reason="root leaf",
            tie_break_method="none",
        ),
        ScoredFileEntry(
            path="src/app.py",
            tier_index=1,
            confidence="medium",
            confidence_reason="core logic",
            tie_break_method="domain",
        ),
    ]
    summary = RepoConfidenceSummary(
        high_pct=50.0,
        medium_pct=50.0,
        low_pct=0.0,
        history_available=True,
    )
    return ScoredOrderingResult(
        files=files,
        repo_confidence_summary=summary,
        isolated_files=[],
        cyclic_files=[],
    )


# 1. Ollama provider selection when LLM_PROVIDER=ollama
def test_ollama_provider_selection_when_configured():
    mock_resp = httpx.Response(
        status_code=200,
        json={"models": [{"name": "llama3.2:3b"}, {"name": "mistral:latest"}]},
        request=httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
    )
    with patch.dict(os.environ, {"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "llama3.2:3b"}):
        with patch("httpx.Client.get", return_value=mock_resp):
            provider = get_default_llm_provider()
            assert provider is not None
            assert callable(provider)


# 2. Provider unavailable or misconfigured
def test_provider_unavailable_or_misconfigured():
    # Case A: LLM_PROVIDER is unset or random
    with patch.dict(os.environ, {"LLM_PROVIDER": ""}, clear=False):
        assert get_default_llm_provider() is None

    with patch.dict(os.environ, {"LLM_PROVIDER": "unsupported_provider"}):
        assert get_default_llm_provider() is None

    # Case B: LLM_PROVIDER=ollama but daemon probe times out / connection refused
    with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
        with patch("httpx.Client.get", side_effect=httpx.ConnectError("Connection refused")):
            assert get_default_llm_provider() is None


# 3. Successful LLM narration
def test_successful_llm_narration(sample_scored):
    valid_markdown = """# Architecture Overview
This system starts with configuration and runs an application handler.

### Milestone 1: Base Configuration
**Role:** Implement `src/config.py` as an isolated entrypoint with zero internal prerequisites.

### Milestone 2: Core Application Logic
**Role:** Build `src/app.py` consuming config definitions to expose service interfaces.
"""
    mock_llm = MagicMock(return_value=valid_markdown)
    engine = NarrationEngine(time_budget=60.0)
    result = engine.generate_narration(
        scored_result=sample_scored,
        llm_provider=mock_llm,
    )

    assert result.source == "llm"
    assert len(result.steps) == 2
    assert "src/config.py" in result.steps[0].pedagogical_explanation
    assert "src/app.py" in result.steps[1].pedagogical_explanation


# 4. Provider timeout
def test_provider_timeout_falls_back_to_template(sample_scored):
    def slow_llm(sys_prompt, user_prompt):
        time.sleep(0.05)
        return "too slow"

    engine = NarrationEngine(time_budget=0.01)  # 10ms budget
    result = engine.generate_narration(
        scored_result=sample_scored,
        llm_provider=slow_llm,
    )

    assert result.source == "template"
    assert engine._provider_failed is True


# 5. Provider exception
def test_provider_exception_falls_back_to_template(sample_scored):
    def failing_llm(sys_prompt, user_prompt):
        raise RuntimeError("GPU memory exhausted")

    engine = NarrationEngine(time_budget=60.0)
    result = engine.generate_narration(
        scored_result=sample_scored,
        llm_provider=failing_llm,
    )

    assert result.source == "template"
    assert engine._provider_failed is True


# 6. Invalid or incomplete LLM output
def test_incomplete_llm_output_triggers_fallback(sample_scored):
    # Missing milestone 2 completely
    incomplete_markdown = """# Overview
Partial summary.
### Milestone 1: Only Step 1
**Role:** Implement `src/config.py`.
"""
    mock_llm = MagicMock(return_value=incomplete_markdown)
    engine = NarrationEngine(time_budget=60.0)
    result = engine.generate_narration(
        scored_result=sample_scored,
        llm_provider=mock_llm,
    )

    # Honesty calibration: because milestone 2 fell back, final source must be template
    assert result.source == "template"


# 7. Template fallback correctly identified
def test_template_fallback_correctly_identified(sample_scored):
    engine = NarrationEngine()
    result = engine.generate_narration(
        scored_result=sample_scored,
        llm_provider=None,
    )
    assert result.source == "template"
    assert len(result.steps) == 2


# 8. Narration source propagating into final report and graph
def test_narration_source_propagates_into_report_and_graph(sample_scored):
    valid_markdown = """# Architecture Overview
This system starts with configuration and runs an application handler.

### Milestone 1: Base Configuration
**Role:** Implement `src/config.py` as an isolated entrypoint with zero internal prerequisites.

### Milestone 2: Core Application Logic
**Role:** Build `src/app.py` consuming config definitions to expose service interfaces.
"""
    mock_llm = MagicMock(return_value=valid_markdown)
    files = {"src/config.py": "ENV = 'dev'\n", "src/app.py": "from src.config import ENV\n"}
    orchestrator = PipelineOrchestrator()
    res = orchestrator.run_pipeline(
        repo_name="org/demo",
        file_paths=list(files.keys()),
        file_contents=files,
        llm_provider=mock_llm,
    )

    assert res.success is True
    assert res.narration_source == "llm"
    assert res.report is not None
    assert res.report.narration_source == "llm"
    assert res.graph_output.get("narration_source") == "llm"
    assert "<!-- narration_source: llm -->" in res.markdown_output


# 9. Job status and persisted artifacts after success
def test_job_status_and_persisted_artifacts(test_db, test_user):
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=test_user.id,
            repo_url="https://github.com/org/test-repo",
            status="pending",
        )
        job_id = job.id

        graph_payload = {"nodes": [{"id": "a"}], "edges": [], "narration_source": "llm"}
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job_id,
            status="completed",
            report_markdown="# Done\n<!-- narration_source: llm -->\n",
            graph_data=graph_payload,
            execution_time_seconds=12.5,
        )

        saved = AnalysisJobRepository.get_job_by_id(session, job_id)
        assert saved.status == "completed"
        assert saved.narration_source == "llm"
        assert saved.execution_time_seconds == 12.5


# 10. Job status and error information after failure
def test_job_status_and_error_info_after_failure(test_db, test_user):
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=test_user.id,
            repo_url="https://github.com/org/fail-repo",
            status="pending",
        )
        job_id = job.id

        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job_id,
            status="failed",
            error_message="Failed during AST parsing.",
            failed_stage="stage_3",
            execution_time_seconds=3.2,
        )

        saved = AnalysisJobRepository.get_job_by_id(session, job_id)
        assert saved.status == "failed"
        assert saved.failed_stage == "stage_3"
        assert saved.error_message == "Failed during AST parsing."


# 11. Progress/SSE terminal events for success and failure
def test_progress_sse_completed_job_terminal_event(client, test_user, test_db):
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=test_user.id,
            repo_url="https://github.com/org/completed-repo",
            status="completed",
        )
        job_id = job.id

    token = create_access_token(user_id=test_user.id, github_id=test_user.github_id, github_username=test_user.github_username)
    client.cookies.set("access_token", token)

    resp = client.get(f"/api/analyses/{job_id}/events")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert resp.headers.get("cache-control") == "no-cache"

    lines = [line for line in resp.text.split("\n") if line.startswith("data:")]
    assert len(lines) == 1
    event_data = json.loads(lines[0].replace("data: ", ""))
    assert event_data["type"] == "completed"
    assert event_data["percentage"] == 100


def test_progress_sse_failed_job_terminal_event(client, test_user, test_db):
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=test_user.id,
            repo_url="https://github.com/org/failed-repo",
            status="failed",
        )
        job.failed_stage = "stage_1"
        job.error_message = "Git clone sandbox error"
        session.commit()
        job_id = job.id

    token = create_access_token(user_id=test_user.id, github_id=test_user.github_id, github_username=test_user.github_username)
    client.cookies.set("access_token", token)

    resp = client.get(f"/api/analyses/{job_id}/events")
    assert resp.status_code == 200
    lines = [line for line in resp.text.split("\n") if line.startswith("data:")]
    assert len(lines) == 1
    event_data = json.loads(lines[0].replace("data: ", ""))
    # Strictly must be 'failed', NEVER 'completed'
    assert event_data["type"] == "failed"
    assert event_data["failed_stage"] == "stage_1"
    assert "Git clone" in event_data["message"]


# 12. Analysis status polling endpoint
def test_analysis_status_endpoint(client, test_user, test_db):
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=test_user.id,
            repo_url="https://github.com/org/poll-repo",
            status="completed",
        )
        job_id = job.id

    token = create_access_token(user_id=test_user.id, github_id=test_user.github_id, github_username=test_user.github_username)
    client.cookies.set("access_token", token)

    resp = client.get(f"/api/analyses/{job_id}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["status"] == "completed"
    assert "narration_source" in data


# 13. Narration time budget environment variable
def test_narration_time_budget_env_var(monkeypatch):
    """Default is 60; setting the env var NARRATION_TIME_BUDGET_SECONDS to 900 gives 900."""
    monkeypatch.delenv("NARRATION_TIME_BUDGET_SECONDS", raising=False)
    engine_default = NarrationEngine()
    assert engine_default.time_budget == 60

    monkeypatch.setenv("NARRATION_TIME_BUDGET_SECONDS", "900")
    engine_custom = NarrationEngine()
    assert engine_custom.time_budget == 900

