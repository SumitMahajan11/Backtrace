"""Tests for Retry Guard Order, Status Concurrency Protection, and Billing Gate Rollback.

Covers:
- retry on a completed job: 409, report text unchanged, usage unchanged
- retry on a pending/running job: 409, usage unchanged
- two retries in a row on a failed job: first OK, second 409, usage +1 in total
- retry of another user's job: 403/404, nothing changes
- at 5/5: blocked, job stays "failed" with its error_message intact
"""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user, get_current_user_optional, get_db
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, UserModel
from app.security.auth import create_access_token
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.billing_repository import BillingRepository
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
def test_db_session(test_db):
    TestingSessionLocal, _ = test_db
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


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
def create_user(test_db):
    SessionLocal, _ = test_db

    def _create(github_id: int, username: str) -> UserModel:
        with SessionLocal() as session:
            user = UserRepository.upsert_github_user(
                session=session,
                github_id=github_id,
                github_username=username,
                email=f"{username}@example.com",
                avatar_url=f"https://avatars.example.com/{username}",
            )
            session.commit()
            session.refresh(user)
            return user

    return _create


def test_retry_completed_job_returns_409(client, create_user, test_db):
    """Retry on a completed job: 409, report text unchanged, usage unchanged."""
    user = create_user(github_id=7701, username="retry_user_comp")
    SessionLocal, _ = test_db
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    client.cookies.set("access_token", token)

    initial_report = "# Original Completed Architecture Report\n\nAll tiers structurally verified."

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/fastapi/fastapi",
            status="completed",
        )
        job.markdown_output = initial_report
        session.commit()
        job_id = job.id

        initial_usage = BillingRepository.get_monthly_usage_count(session, user.id)

    # 1. API endpoint retry attempt
    resp_api = client.post(f"/api/analyses/{job_id}/retry", headers=headers)
    assert resp_api.status_code == 409
    assert "This analysis can't be retried" in resp_api.text

    # 2. UI endpoint retry attempt (JSON request)
    resp_ui_json = client.post(f"/analyses/{job_id}/retry", headers={"Accept": "application/json"})
    assert resp_ui_json.status_code == 409

    # 3. UI endpoint retry attempt (Browser redirect request)
    resp_ui_redirect = client.post(f"/analyses/{job_id}/retry", follow_redirects=False)
    assert resp_ui_redirect.status_code == 302
    assert "error=This+analysis+can%27t+be+retried" in resp_ui_redirect.headers["location"] or "error=This+analysis+can't+be+retried" in resp_ui_redirect.headers["location"]

    # Verify DB state: report text and status unchanged, usage unchanged
    with SessionLocal() as session:
        job_db = AnalysisJobRepository.get_job_by_id(session, job_id)
        assert job_db.status == "completed"
        assert job_db.markdown_output == initial_report
        final_usage = BillingRepository.get_monthly_usage_count(session, user.id)
        assert final_usage == initial_usage


def test_retry_pending_or_running_job_returns_409(client, create_user, test_db):
    """Retry on a pending/running job: 409, usage unchanged."""
    user = create_user(github_id=7702, username="retry_user_running")
    SessionLocal, _ = test_db
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    with SessionLocal() as session:
        job_running = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/pallets/flask",
            status="running",
        )
        job_pending = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/pallets/click",
            status="pending",
        )
        session.commit()
        running_id, pending_id = job_running.id, job_pending.id
        initial_usage = BillingRepository.get_monthly_usage_count(session, user.id)

    # Attempt retry on running job
    resp_running = client.post(f"/api/analyses/{running_id}/retry", headers=headers)
    assert resp_running.status_code == 409

    # Attempt retry on pending job
    resp_pending = client.post(f"/api/analyses/{pending_id}/retry", headers=headers)
    assert resp_pending.status_code == 409

    # Verify DB state & usage unchanged
    with SessionLocal() as session:
        j_run = AnalysisJobRepository.get_job_by_id(session, running_id)
        j_pen = AnalysisJobRepository.get_job_by_id(session, pending_id)
        assert j_run.status == "running"
        assert j_pen.status == "pending"
        final_usage = BillingRepository.get_monthly_usage_count(session, user.id)
        assert final_usage == initial_usage


def test_two_retries_in_a_row_on_failed_job(client, create_user, test_db):
    """Two retries in a row on a failed job: first OK, second 409, usage +1 in total."""
    user = create_user(github_id=7703, username="retry_user_double")
    SessionLocal, _ = test_db
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/django/django",
            status="failed",
        )
        job.error_message = "Git shallow clone timed out"
        session.commit()
        job_id = job.id
        initial_usage = BillingRepository.get_monthly_usage_count(session, user.id)

    # First retry: MUST SUCCEED (200 JSON, pending status)
    resp1 = client.post(f"/api/analyses/{job_id}/retry", headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["success"] is True
    assert data1["status"] == "pending"

    # Second retry immediately after: MUST RETURN 409 (job is now pending, not failed/cancelled)
    resp2 = client.post(f"/api/analyses/{job_id}/retry", headers=headers)
    assert resp2.status_code == 409
    assert "This analysis can't be retried" in resp2.text

    # Total usage must increase by EXACTLY +1
    with SessionLocal() as session:
        final_usage = BillingRepository.get_monthly_usage_count(session, user.id)
        assert final_usage == initial_usage + 1


def test_retry_another_user_job_forbidden_and_not_found(client, create_user, test_db):
    """Retry of another user's job: 403/404, nothing changes."""
    user_owner = create_user(github_id=7704, username="owner_user")
    user_attacker = create_user(github_id=7705, username="attacker_user")
    SessionLocal, _ = test_db

    attacker_token = create_access_token(user_id=user_attacker.id, github_id=user_attacker.github_id, github_username=user_attacker.github_username)
    attacker_headers = {"Authorization": f"Bearer {attacker_token}", "Accept": "application/json"}

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user_owner.id,
            repo_url="https://github.com/secret/repo",
            status="failed",
        )
        job.error_message = "Owner proprietary failure"
        session.commit()
        job_id = job.id

        owner_usage_before = BillingRepository.get_monthly_usage_count(session, user_owner.id)
        attacker_usage_before = BillingRepository.get_monthly_usage_count(session, user_attacker.id)

    # Attacker tries to retry owner's job -> 403 Forbidden
    resp_idor = client.post(f"/api/analyses/{job_id}/retry", headers=attacker_headers)
    assert resp_idor.status_code == 403
    assert "Access forbidden" in resp_idor.text

    # Retry non-existent job -> 404 Not Found
    resp_404 = client.post("/api/analyses/99999999/retry", headers=attacker_headers)
    assert resp_404.status_code == 404

    # Verify DB state: job still failed, error_message unchanged, usages unchanged
    with SessionLocal() as session:
        job_db = AnalysisJobRepository.get_job_by_id(session, job_id)
        assert job_db.status == "failed"
        assert job_db.error_message == "Owner proprietary failure"
        assert BillingRepository.get_monthly_usage_count(session, user_owner.id) == owner_usage_before
        assert BillingRepository.get_monthly_usage_count(session, user_attacker.id) == attacker_usage_before


def test_retry_at_quota_limit_blocked_job_stays_failed(client, create_user, test_db):
    """At 5/5: blocked, job stays 'failed' with its error_message intact."""
    user = create_user(github_id=7706, username="quota_max_user")
    SessionLocal, _ = test_db
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    with SessionLocal() as session:
        # Pre-consume all 5 free analyses
        for _ in range(5):
            BillingRepository.record_usage_event(session, user_id=user.id, event_type="repo_analysis")
        session.commit()

        assert BillingRepository.get_monthly_usage_count(session, user.id) == 5

        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/large/repo",
            status="failed",
        )
        job.error_message = "Parser OutOfMemoryError on file ast"
        session.commit()
        job_id = job.id

    # Attempt retry at quota limit -> 403 Forbidden
    resp = client.post(f"/api/analyses/{job_id}/retry", headers=headers)
    assert resp.status_code == 403
    assert "You've used all 5 analyses this month" in resp.text

    # Assert job rolled back and stays "failed" with original error_message intact
    with SessionLocal() as session:
        refreshed_job = AnalysisJobRepository.get_job_by_id(session, job_id)
        assert refreshed_job.status == "failed"
        assert refreshed_job.error_message == "Parser OutOfMemoryError on file ast"
        assert BillingRepository.get_monthly_usage_count(session, user.id) == 5
