"""Unit and Integration Tests for Piston Health Check and Graceful Degradation (Prompt 21)."""

import json
import time
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, UserModel
from app.security.auth import create_access_token
from app.services.execution_verifier import ExecutionVerifier, ExecutionVerifierConnectionError
from app.services.grading_engine import GradingEngine
from app.services.piston_health import PistonHealthMonitor, piston_health_monitor
from app.services.structural_verifier import StructuralVerifier


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
def auth_user(test_db):
    TestingSessionLocal, _ = test_db
    with TestingSessionLocal() as session:
        user = UserModel(
            github_id=88888,
            github_username="test_health_user",
            email="health@example.com",
            avatar_url="https://example.com/avatar.png",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        job = AnalysisJobModel(
            user_id=user.id,
            repo_name="health-repo",
            github_url="https://github.com/test/health-repo",
            status="completed",
            run_id="run_health_01",
            graph_output_json=json.dumps({
                "milestones": [
                    {"tier": 1, "name": "Tier 1", "test_code": "assert solution() == 'tier1'"},
                    {"tier": 3, "name": "Tier 3", "expected_symbols": ["solve"]}
                ],
                "nodes": [
                    {"id": "solve", "type": "function", "tier": 3, "name": "solve", "exports": ["solve"]}
                ]
            }),
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        token = create_access_token(
            user_id=user.id,
            github_id=user.github_id,
            github_username=user.github_username,
        )
        return {"user": user, "job": job, "token": token}


def test_piston_health_monitor_healthy_and_unhealthy():
    """Verifies that PistonHealthMonitor records real up/down states and latencies."""
    monitor = PistonHealthMonitor(piston_url="http://127.0.0.1:2000")
    
    # Test healthy mock
    with patch("httpx.Client.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"language": "python", "version": "3.10.0"}]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        
        status = monitor.check_health_sync()
        assert status["status"] == "healthy"
        assert status["is_available"] is True
        assert status["runtimes_count"] == 1
        assert monitor.is_healthy is True

    # Test unhealthy mock
    with patch("httpx.Client.get", side_effect=Exception("Connection refused")):
        status = monitor.check_health_sync()
        assert status["status"] == "unhealthy"
        assert status["is_available"] is False
        assert "error" in status
        assert monitor.is_healthy is False


def test_health_endpoint_surfaces_piston_state(client):
    """Verifies that /health endpoint includes Piston's operational status."""
    with patch.object(piston_health_monitor, "get_status") as mock_status:
        mock_status.return_value = {
            "status": "healthy",
            "is_available": True,
            "last_checked_at": "2026-09-18T00:00:00Z",
            "latency_ms": 1.25,
            "runtimes_count": 8,
        }
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "piston_sandbox" in data["checks"]
        assert data["checks"]["piston_sandbox"]["status"] == "healthy"
        assert data["checks"]["piston_sandbox"]["runtimes_count"] == 8


def test_run_fast_fails_when_piston_is_down(client, auth_user):
    """Verifies that /run fails fast with 503 (<50ms) when Piston is down and local fallback is disabled."""
    from unittest.mock import PropertyMock
    job_id = auth_user["job"].id
    headers = {"Authorization": f"Bearer {auth_user['token']}"}
    
    with patch.object(PistonHealthMonitor, "is_healthy", new_callable=PropertyMock, return_value=False), \
         patch("app.api.attempts.execution_verifier.allow_local_fallback", False):
        start = time.perf_counter()
        resp = client.post(
            f"/api/attempts/{job_id}/1/run",
            headers=headers,
            json={"submitted_code": "print('hello')", "language": "python"},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        
        assert resp.status_code == 503
        assert "Code execution sandbox is currently unavailable" in resp.json()["detail"]
        assert elapsed_ms < 250.0  # Fast-fail must not wait for 3000ms timeout


def test_submit_execution_dependent_fast_fails_when_piston_is_down(client, auth_user):
    """Verifies that execution-dependent /submit (Tier 1 real_tests) fails fast with 503 when Piston is down and local fallback is disabled."""
    from unittest.mock import PropertyMock
    job_id = auth_user["job"].id
    headers = {"Authorization": f"Bearer {auth_user['token']}"}
    
    with patch.object(PistonHealthMonitor, "is_healthy", new_callable=PropertyMock, return_value=False), \
         patch("app.api.attempts.grading_engine.exec_verifier.allow_local_fallback", False):
        start = time.perf_counter()
        resp = client.post(
            f"/api/attempts/{job_id}/1",
            headers=headers,
            json={"submitted_code": "def solution(): return 'tier1'", "language": "python"},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        
        assert resp.status_code == 503
        assert "Code execution sandbox is currently unavailable" in resp.json()["detail"]
        assert elapsed_ms < 250.0


def test_submit_tier3_structural_succeeds_when_piston_is_down(client, auth_user):
    """Verifies that Tier 3 (structural_only) grading succeeds even when Piston is down."""
    from unittest.mock import PropertyMock
    job_id = auth_user["job"].id
    headers = {"Authorization": f"Bearer {auth_user['token']}"}
    
    with patch.object(PistonHealthMonitor, "is_healthy", new_callable=PropertyMock, return_value=False), \
         patch("app.api.attempts.grading_engine.exec_verifier.allow_local_fallback", False):
        resp = client.post(
            f"/api/attempts/{job_id}/3",
            headers=headers,
            json={"submitted_code": "def solve():\n    return 42\n", "language": "python"},
        )
        
        assert resp.status_code == 200
        data = resp.json()
        assert data["attempt"]["status"] == "structurally_verified"
        assert data["grading_details"]["degraded_mode"] is True
        assert data["grading_details"]["passed"] is True
        assert data["grading_method"] == "structural_only"
