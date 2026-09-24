"""Tests for Prompt 6: Dashboard Redesign, Quota Meter, and Retry Flow."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
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


def test_dashboard_unauthenticated_redirect(client):
    """Unauthenticated users visiting /dashboard must be redirected to /login."""
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_dashboard_free_user_empty_state(client, create_user):
    """Free user with no jobs sees empty state and real quota metadata."""
    user = create_user(github_id=888001, username="dash_user1")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text

    # Editorial Header
    assert "Root-Cause Analysis Ledger" in html
    assert "ARCHITECTURE REPORT REPOSITORY PARSING" in html
    assert "Submit version-controlled source archives" in html

    # Quota Status & Renewal
    assert "FREE TIER" in html
    assert "0 / 5 JOBS ALLOTTED" in html
    assert "RENEWS:" in html
    assert "Upgrade to Pro" in html

    # Main Stratum Card
    assert "Reconstruct Repository History" in html
    assert "Detailed Syntax Tree Analysis" in html
    assert "Automatic Tier Grouping" in html
    assert "https://github.com/expressjs/express" in html

    # Empty State Copy
    assert "No analyses yet" in html
    assert "No analyses yet. Paste a GitHub URL above to reconstruct your first build history." in html


def test_dashboard_populated_state(client, create_user, test_db):
    """Dashboard correctly lists completed, running, and failed jobs with accurate action triggers."""
    user = create_user(github_id=888001, username="dash_user1")
    SessionLocal, _ = test_db
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with SessionLocal() as session:
        j1 = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/pallets/flask",
            repo_name="pallets/flask",
            status="completed",
        )
        j2 = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/gin-gonic/gin",
            repo_name="gin-gonic/gin",
            status="running",
        )
        j3 = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/django/django",
            repo_name="django/django",
            status="failed",
        )
        j1_id, j2_id, j3_id = j1.id, j2.id, j3.id

    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text

    # Verify rows & actions
    assert f"/report/{j1_id}" in html
    assert "View Architecture Report" in html
    assert f"/progress/{j2_id}" in html
    assert "Track Progress" in html
    assert f"/analyses/{j3_id}/retry" in html
    assert "Retry Analysis Job" in html


def test_dashboard_paid_user_state(client, create_user, test_db):
    """Paid user sees PRO TIER badge, unlimited quota, and manage subscription link."""
    from datetime import datetime, timedelta, timezone
    user = create_user(github_id=888001, username="dash_user1")
    SessionLocal, _ = test_db
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    future_end = datetime.now(timezone.utc) + timedelta(days=30)
    with SessionLocal() as session:
        BillingRepository.upsert_subscription(
            session=session,
            user_id=user.id,
            stripe_customer_id="cus_test_paid_user",
            stripe_subscription_id="sub_test_paid_user",
            status="active",
            current_period_end=future_end.replace(tzinfo=None),
        )
        session.commit()

    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text

    assert "PRO TIER" in html
    assert "UNLIMITED ANALYSIS JOBS" in html
    assert "Manage Billing" in html


def test_retry_endpoint_ui_success(client, create_user, test_db):
    """POST /analyses/{job_id}/retry resets failed job to pending without consuming extra quota."""
    user = create_user(github_id=888001, username="dash_user1")
    SessionLocal, _ = test_db
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/fastapi/fastapi",
            status="failed",
        )
        job.error_message = "Network timeout during shallow clone"
        job.markdown_output = "# Stale Report"
        job.graph_output_json = '{"stale": true}'
        job.quiz_output_json = '{"questions": ["stale?"]}'
        job.execution_time_seconds = 42.5
        session.commit()
        job_id = job.id

        initial_usage = BillingRepository.get_monthly_usage_count(session, user.id)

    # Post to retry endpoint
    resp = client.post(f"/analyses/{job_id}/retry", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/progress/{job_id}"

    # Verify DB state
    with SessionLocal() as session:
        updated_job = AnalysisJobRepository.get_job_by_id(session, job_id)
        assert updated_job.status == "pending"
        assert updated_job.error_message is None
        assert updated_job.markdown_output == ""
        assert updated_job.graph_output_json == "{}"
        assert updated_job.quiz_output_json == "{}"
        assert updated_job.execution_time_seconds == 0.0
        assert updated_job.run_id.startswith(f"retry_{job_id}_")

        # Quota usage must NOT increase
        final_usage = BillingRepository.get_monthly_usage_count(session, user.id)
        assert final_usage == initial_usage


def test_retry_endpoint_api_success(client, create_user, test_db):
    """POST /api/analyses/{job_id}/retry returns JSON redirect info."""
    user = create_user(github_id=888001, username="dash_user1")
    SessionLocal, _ = test_db
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    headers = {"Authorization": f"Bearer {token}"}

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/encode/uvicorn",
            status="failed",
        )
        job_id = job.id

    resp = client.post(f"/api/analyses/{job_id}/retry", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["job_id"] == job_id
    assert data["status"] == "pending"
    assert data["redirect_url"] == f"/progress/{job_id}"


def test_retry_endpoint_idor_protection(client, create_user, test_db):
    """User B cannot retry User A's failed analysis job (IDOR Defense)."""
    user1 = create_user(github_id=888001, username="dash_user1")
    user2 = create_user(github_id=888002, username="dash_user2")
    SessionLocal, _ = test_db
    u2_token = create_access_token(user_id=user2.id, github_id=user2.github_id, github_username=user2.github_username)
    client.cookies.set("access_token", u2_token)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user1.id,
            repo_url="https://github.com/psf/requests",
            status="failed",
        )
        job_id = job.id

    resp = client.post(f"/analyses/{job_id}/retry")
    assert resp.status_code == 403
    assert "Access forbidden" in resp.text
