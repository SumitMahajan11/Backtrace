"""Tests verifying production deployment preparation requirements (Recheck Round Step 2).

Verifies:
(a) MAX_REPO_MB: over the limit raises IngestionLimitExceededError and under passes
(b) SANDBOX_ENABLED=false: /run returns 503, /health shows disabled, and monitor makes no HTTP calls
(c) Redis timeout choice for rediss:// vs redis://
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, UserModel
from app.models.ingestion import IngestionLimitExceededError
from app.security.auth import create_access_token
from app.security.rate_limiter import RedisTokenBucketRateLimiter
from app.services.ingestion import IngestionService, check_repo_size_preflight, get_max_repo_mb
from app.services.piston_health import PistonHealthMonitor, piston_health_monitor


# -----------------------------------------------------------------------------
# (a) MAX_REPO_MB Tests
# -----------------------------------------------------------------------------

def test_max_repo_mb_ingestion_service_over_and_under(tmp_path, monkeypatch):
    """Verifies that IngestionService enforces max_repo_mb limit."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Create two 600KB files (total 1.2MB, each under 1MB individual file cap)
    chunk = b"X" * (600 * 1024)
    (repo_dir / "file1.txt").write_bytes(chunk)
    (repo_dir / "file2.txt").write_bytes(chunk)

    # 1. Over the limit (max_repo_mb = 1 MB -> 1.2MB exceeds cap)
    service_over = IngestionService(max_repo_mb=1)
    with pytest.raises(IngestionLimitExceededError) as exc_info:
        service_over._process_file_tree(repo_dir)
    assert "exceeds maximum allowed cap of 1 MB" in str(exc_info.value)

    # 2. Under the limit (max_repo_mb = 5 MB -> 1.2MB is allowed)
    service_under = IngestionService(max_repo_mb=5)
    file_tree, file_contents, skipped = service_under._process_file_tree(repo_dir)
    assert len(file_tree) == 2
    assert "file1.txt" in file_contents
    assert "file2.txt" in file_contents


def test_max_repo_mb_preflight_check_over_and_under(monkeypatch):
    """Verifies that check_repo_size_preflight enforces max_repo_mb on GitHub tree."""
    monkeypatch.setattr("app.services.ingestion.validate_github_url", lambda url: ("org", "repo"))
    monkeypatch.setattr("app.services.ingestion.validate_ssrf", lambda host: None)
    monkeypatch.setenv("MAX_REPO_MB", "2")

    # Mock GitHub API tree response with four 600KB files (total 2.4MB > 2MB limit)
    # Each file is under the 1MB individual file limit so it is not skipped individually
    mock_tree_over = {
        "tree": [
            {"path": "file1.py", "type": "blob", "size": 600 * 1024},
            {"path": "file2.py", "type": "blob", "size": 600 * 1024},
            {"path": "file3.py", "type": "blob", "size": 600 * 1024},
            {"path": "file4.py", "type": "blob", "size": 600 * 1024},
        ],
        "truncated": False,
    }

    mock_resp_over = MagicMock()
    mock_resp_over.json.return_value = mock_tree_over
    mock_resp_over.status_code = 200

    # Preflight over limit raises IngestionLimitExceededError
    with patch("httpx.Client.get", return_value=mock_resp_over):
        with pytest.raises(IngestionLimitExceededError) as exc_info:
            check_repo_size_preflight("https://github.com/org/repo")
        assert "exceeds maximum allowed cap of 2 MB" in str(exc_info.value)

    # Preflight under limit passes (single 600KB file < 2MB limit)
    mock_tree_under = {
        "tree": [
            {"path": "file1.py", "type": "blob", "size": 600 * 1024},
        ],
        "truncated": False,
    }
    mock_resp_under = MagicMock()
    mock_resp_under.json.return_value = mock_tree_under
    mock_resp_under.status_code = 200

    with patch("httpx.Client.get", return_value=mock_resp_under):
        count = check_repo_size_preflight("https://github.com/org/repo")
        assert count == 1


# -----------------------------------------------------------------------------
# (b) SANDBOX_ENABLED=false Tests
# -----------------------------------------------------------------------------

def test_sandbox_disabled_monitor_makes_no_http_calls(monkeypatch):
    """Verifies that when SANDBOX_ENABLED=false, the monitor makes no HTTP calls and reports disabled."""
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    monitor = PistonHealthMonitor(piston_url="http://piston:2000")

    assert monitor.is_sandbox_enabled() is False
    assert monitor.is_healthy is False

    with patch("httpx.Client.get") as mock_get:
        # Synchronous health check should return immediately without making HTTP calls
        sync_status = monitor.check_health_sync()
        assert sync_status["status"] == "disabled"
        assert sync_status["is_available"] is False
        assert mock_get.call_count == 0

        # Background task should exit immediately without polling
        monitor.start_background_task()
        assert mock_get.call_count == 0

    # Status dictionary check
    status = monitor.get_status()
    assert status["status"] == "disabled"
    assert status["is_available"] is False


@pytest.mark.asyncio
async def test_sandbox_disabled_async_monitor_makes_no_http_calls(monkeypatch):
    """Verifies that async health check also makes no HTTP calls when sandbox is disabled."""
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    monitor = PistonHealthMonitor(piston_url="http://piston:2000")

    with patch("httpx.AsyncClient.get") as mock_async_get:
        async_status = await monitor.check_health_async()
        assert async_status["status"] == "disabled"
        assert async_status["is_available"] is False
        assert mock_async_get.call_count == 0


def test_sandbox_disabled_health_endpoint(monkeypatch):
    """Verifies that GET /health shows piston disabled when SANDBOX_ENABLED=false."""
    monkeypatch.setenv("SANDBOX_ENABLED", "false")

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "checks" in data
        assert "piston_sandbox" in data["checks"]
        assert data["checks"]["piston_sandbox"]["status"] == "disabled"
        assert data["checks"]["piston_sandbox"]["is_available"] is False


def test_sandbox_disabled_run_returns_503(monkeypatch):
    """Verifies that POST /api/attempts/{job_id}/{milestone_tier}/run returns 503 when SANDBOX_ENABLED=false."""
    monkeypatch.setenv("SANDBOX_ENABLED", "false")

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestingSessionLocal() as session:
            user = UserModel(github_id=7777, github_username="sandbox_user", email="user@example.com")
            session.add(user)
            session.commit()
            session.refresh(user)

            job = AnalysisJobModel(
                user_id=user.id,
                repo_name="sandbox-repo",
                github_url="https://github.com/org/sandbox-repo",
                status="completed",
                run_id="run_sandbox_01",
            )
            session.add(job)
            session.commit()
            session.refresh(job)

            user_id = user.id
            job_id = job.id

        token = create_access_token(user_id=user_id, github_id=7777, github_username="sandbox_user")

        with TestClient(app) as client:
            resp = client.post(
                f"/api/attempts/{job_id}/1/run",
                json={"submitted_code": "def solution(): return 42", "language": "python"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 503
            assert "detail" in resp.json()
            assert "disabled" in resp.json()["detail"].lower() or "unavailable" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


# -----------------------------------------------------------------------------
# (c) Redis Timeout Choice Tests (rediss:// vs redis://)
# -----------------------------------------------------------------------------

def test_redis_timeout_selection_rediss_vs_redis():
    """Verifies that Redis rate limiter applies >=1.5s timeout for rediss:// and <=0.05s for redis://."""
    # 1. Unencrypted redis:// URL (local/private network)
    with patch("redis.ConnectionPool.from_url") as mock_from_url:
        _ = RedisTokenBucketRateLimiter(
            redis_url="redis://127.0.0.1:6379/0",
            redis_timeout=1.5,
        )
        assert mock_from_url.call_count == 1
        _, kwargs_redis = mock_from_url.call_args
        assert kwargs_redis["socket_connect_timeout"] <= 0.05
        assert kwargs_redis["socket_timeout"] <= 0.05

    # 2. TLS encrypted rediss:// URL (Upstash / cloud managed)
    with patch("redis.ConnectionPool.from_url") as mock_from_url:
        _ = RedisTokenBucketRateLimiter(
            redis_url="rediss://default:password@eu2-active-redis.upstash.io:6379",
            redis_timeout=1.0,
        )
        assert mock_from_url.call_count == 1
        _, kwargs_rediss = mock_from_url.call_args
        assert kwargs_rediss["socket_connect_timeout"] >= 1.5
        assert kwargs_rediss["socket_timeout"] >= 1.5
