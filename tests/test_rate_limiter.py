"""Unit and Integration Tests for Distributed Redis-Backed Rate Limiting (Prompt 27)."""

import json
import time
from unittest.mock import MagicMock, patch
import pytest
import fakeredis
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, UserModel
from app.security.auth import create_access_token
from app.security.rate_limiter import (
    CircuitBreakerAlerter,
    RedisTokenBucketRateLimiter,
    TokenBucketRateLimiter,
    execution_rate_limiter,
)


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    execution_rate_limiter.reset_all()
    yield
    execution_rate_limiter.reset_all()


@pytest.fixture
def fake_redis_client():
    """Provides an in-memory Redis server supporting Lua script execution."""
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    client.flushall()


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
def auth_users(test_db):
    TestingSessionLocal, _ = test_db
    with TestingSessionLocal() as session:
        user_a = UserModel(
            github_id=11111,
            github_username="user_alpha",
            email="alpha@example.com",
            avatar_url="https://example.com/alpha.png",
        )
        user_b = UserModel(
            github_id=22222,
            github_username="user_beta",
            email="beta@example.com",
            avatar_url="https://example.com/beta.png",
        )
        session.add_all([user_a, user_b])
        session.commit()
        session.refresh(user_a)
        session.refresh(user_b)

        job_a = AnalysisJobModel(
            user_id=user_a.id,
            repo_name="repo_a",
            github_url="https://github.com/test/repo_a",
            status="completed",
            run_id="run_a_01",
            graph_output_json=json.dumps({
                "milestones": [{"tier": 3, "name": "Tier 3"}],
                "nodes": [{"id": "func_a", "type": "function", "tier": 3, "exports": ["func_a"]}]
            }),
        )
        job_b = AnalysisJobModel(
            user_id=user_b.id,
            repo_name="repo_b",
            github_url="https://github.com/test/repo_b",
            status="completed",
            run_id="run_b_01",
            graph_output_json=json.dumps({
                "milestones": [{"tier": 3, "name": "Tier 3"}],
                "nodes": [{"id": "func_b", "type": "function", "tier": 3, "exports": ["func_b"]}]
            }),
        )
        session.add_all([job_a, job_b])
        session.commit()
        session.refresh(job_a)
        session.refresh(job_b)

        token_a = create_access_token(user_id=user_a.id, github_id=user_a.github_id, github_username=user_a.github_username)
        token_b = create_access_token(user_id=user_b.id, github_id=user_b.github_id, github_username=user_b.github_username)

        return {
            "user_a": user_a,
            "job_a": job_a,
            "token_a": token_a,
            "user_b": user_b,
            "job_b": job_b,
            "token_b": token_b,
        }


def test_redis_lua_token_bucket_burst_and_exhaustion(fake_redis_client):
    """Verifies atomic Redis Lua execution allowing capacity bursts and rejecting when empty."""
    limiter = RedisTokenBucketRateLimiter(
        redis_client=fake_redis_client,
        capacity=3,
        refill_per_minute=3,
        fail_open=True,
    )
    
    # First 3 requests must succeed
    assert limiter.check_rate_limit("user:1").allowed is True
    assert limiter.check_rate_limit("user:1").allowed is True
    assert limiter.check_rate_limit("user:1").allowed is True
    
    # 4th request must be rejected
    res = limiter.check_rate_limit("user:1")
    assert res.allowed is False
    assert res.remaining == 0
    assert res.retry_after >= 1


def test_redis_token_bucket_user_isolation(fake_redis_client):
    """Verifies that User A hitting the limit has zero effect on User B."""
    limiter = RedisTokenBucketRateLimiter(
        redis_client=fake_redis_client,
        capacity=2,
        refill_per_minute=2,
        fail_open=True,
    )
    
    # User A exhausts tokens
    assert limiter.check_rate_limit("user:A").allowed is True
    assert limiter.check_rate_limit("user:A").allowed is True
    assert limiter.check_rate_limit("user:A").allowed is False
    
    # User B should still have full quota
    assert limiter.check_rate_limit("user:B").allowed is True
    assert limiter.check_rate_limit("user:B").allowed is True


def test_redis_fail_open_on_connection_error():
    """Verifies that Redis connection or execution errors fail open to protect user traffic."""
    broken_redis = MagicMock()
    broken_redis.register_script.side_effect = Exception("ConnectionRefusedError: Redis is down")
    
    limiter = RedisTokenBucketRateLimiter(
        redis_client=broken_redis,
        capacity=5,
        refill_per_minute=5,
        fail_open=True,
    )
    
    # Should fail open cleanly without raising an exception to the caller
    res = limiter.check_rate_limit("user:99")
    assert res.allowed is True


def test_circuit_breaker_alert_trigger_on_threshold_breach():
    """Verifies that repeated fail-open bypasses trigger a security alert."""
    alerter = CircuitBreakerAlerter(threshold=3, window_seconds=10.0)
    
    with patch.object(alerter, "_trigger_security_alert") as mock_alert:
        err = Exception("Redis connection timeout")
        # 2 failures: under threshold, no alert
        alerter.record_failure(err, "user:1")
        alerter.record_failure(err, "user:1")
        assert mock_alert.call_count == 0
        
        # 3rd failure: reaches threshold, triggers alert
        alerter.record_failure(err, "user:1")
        assert mock_alert.call_count == 1
        
        stats = alerter.get_stats()
        assert stats["recent_bypasses_window"] == 3
        assert stats["total_bypasses"] == 3
        assert stats["consecutive_failures"] == 3


def test_api_rate_limiting_live_rejection_and_isolation(client, auth_users, fake_redis_client):
    """
    Live API demonstration with distributed limiter:
    - User A fires requests beyond capacity and receives HTTP 429 with standard headers.
    - Concurrent User B fires requests and receives HTTP 200 without interference.
    """
    token_a = auth_users["token_a"]
    job_a_id = auth_users["job_a"].id
    headers_a = {"Authorization": f"Bearer {token_a}"}

    token_b = auth_users["token_b"]
    job_b_id = auth_users["job_b"].id
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Inject fake_redis_client into execution_rate_limiter
    execution_rate_limiter._redis = fake_redis_client
    execution_rate_limiter._script = fake_redis_client.register_script(execution_rate_limiter._script._script if execution_rate_limiter._script else None or "") if hasattr(execution_rate_limiter._script, "_script") else None
    execution_rate_limiter._init_redis(redis_client=fake_redis_client)

    # Mock Piston execution verifier so tests don't depend on live Piston socket
    with patch("app.services.execution_verifier.ExecutionVerifier.execute") as mock_exec:
        mock_exec.return_value = {
            "stdout": "OK",
            "stderr": "",
            "exit_code": 0,
            "execution_time_ms": 15.0,
            "status": "success",
            "truncated": False,
        }

        # User A makes 10 successful requests (capacity = 10)
        for i in range(10):
            resp = client.post(
                f"/api/attempts/{job_a_id}/1/run",
                headers=headers_a,
                json={"submitted_code": f"print({i})", "language": "python"},
            )
            assert resp.status_code == 200, f"Request {i+1} failed unexpectedly with {resp.status_code}"

        # 11th request from User A MUST be rejected with HTTP 429
        resp_429 = client.post(
            f"/api/attempts/{job_a_id}/1/run",
            headers=headers_a,
            json={"submitted_code": "print('burst limit breached')", "language": "python"},
        )
        assert resp_429.status_code == 429
        assert "Rate limit exceeded" in resp_429.json()["detail"]
        assert "Retry-After" in resp_429.headers
        assert "X-RateLimit-Limit" in resp_429.headers
        assert resp_429.headers["X-RateLimit-Remaining"] == "0"

        # Concurrent request from User B MUST succeed with HTTP 200 (proving isolation)
        resp_b = client.post(
            f"/api/attempts/{job_b_id}/1/run",
            headers=headers_b,
            json={"submitted_code": "print('User B normal execution')", "language": "python"},
        )
        assert resp_b.status_code == 200
