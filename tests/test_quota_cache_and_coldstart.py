"""Tests for cache re-analysis, failure quota refunds, quota UI/gating, and cold start handling."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user_optional, get_db
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, MilestoneAttemptModel, UserModel
from app.services.billing_service import BillingService
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.billing_repository import BillingRepository
from app.ui.components import dashboard_view, report_view


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


# =========================================================================
# Part A: Cache Re-analysis Tests
# =========================================================================

def test_cache_reanalysis_identical_repo_and_commit(client, test_db_session):
    """
    Two submissions of an identical repo and commit give one job,
    quota used stays 1, and the second response redirects to the existing report.
    Re-analyze anyway option only when commit is unchanged charges quota.
    """
    user = UserModel(github_id=9001, github_username="cacher_user", email="cacher@test.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    app.dependency_overrides[get_current_user_optional] = lambda: user
    app.dependency_overrides[get_db] = lambda: test_db_session

    try:
        with patch("app.services.ingestion.check_repo_size_preflight", return_value=10), \
             patch("app.services.cached_ingestion.get_remote_head_commit", return_value="sha_abc_123"):

            # 1. First submission
            resp1 = client.post(
                "/analyses/submit",
                data={
                    "repo_url": "https://github.com/owner/demo-repo",
                    "commit_ref": "main",
                },
                follow_redirects=False,
            )
            assert resp1.status_code == 302
            assert "/progress/" in resp1.headers["location"]
            first_job_id = int(resp1.headers["location"].split("/")[-1])

            # Check job created and quota consumed
            jobs = AnalysisJobRepository.get_jobs_for_user(test_db_session, user.id)
            assert len(jobs) == 1
            assert jobs[0].resolved_sha == "sha_abc_123"
            assert user.quota_used == 1

            # Mark first job completed and record a milestone attempt to track learning progress
            AnalysisJobRepository.update_job_status(
                test_db_session,
                first_job_id,
                status="completed",
                resolved_sha="sha_abc_123",
            )
            attempt = MilestoneAttemptModel(
                user_id=user.id,
                job_id=first_job_id,
                milestone_tier=1,
                status="structurally_verified",
            )
            test_db_session.add(attempt)
            test_db_session.commit()

            # 2. Second submission: Identical repo and commit
            resp2 = client.post(
                "/analyses/submit",
                data={
                    "repo_url": "https://github.com/owner/demo-repo",
                    "commit_ref": "main",
                },
                follow_redirects=False,
            )

            # Redirects to existing completed report directly
            assert resp2.status_code == 302
            assert resp2.headers["location"] == f"/report/{first_job_id}"

            # Quota used remains 1, jobs count remains 1, learning progress preserved
            assert user.quota_used == 1
            jobs_after = AnalysisJobRepository.get_jobs_for_user(test_db_session, user.id)
            assert len(jobs_after) == 1
            attempts_after = test_db_session.query(MilestoneAttemptModel).filter_by(user_id=user.id).all()
            assert len(attempts_after) == 1

            # 3. Third submission: "Re-analyze anyway" when commit is unchanged
            resp3 = client.post(
                "/analyses/submit",
                data={
                    "repo_url": "https://github.com/owner/demo-repo",
                    "commit_ref": "main",
                    "reanalyze_anyway": "true",
                },
                follow_redirects=False,
            )
            assert resp3.status_code == 302
            assert "/progress/" in resp3.headers["location"]
            second_job_id = int(resp3.headers["location"].split("/")[-1])
            assert second_job_id != first_job_id

            # It DOES charge quota and creates a new job
            assert user.quota_used == 2
            jobs_final = AnalysisJobRepository.get_jobs_for_user(test_db_session, user.id)
            assert len(jobs_final) == 2

    finally:
        app.dependency_overrides.clear()


# =========================================================================
# Part B: Refund on Failure Tests
# =========================================================================

def test_refund_quota_on_job_failure(test_db_session):
    """
    Simulate a job that raises an exception.
    Assert quota_used returns to its previous value in the same transaction that sets failed status.
    """
    user = UserModel(github_id=9002, github_username="failure_user", email="failure@test.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    initial_quota = user.quota_used
    assert initial_quota == 0

    # Job starts: Quota is charged
    allowed, usage, limit, tier = BillingService.check_and_consume_quota(user, test_db_session)
    assert allowed is True
    assert usage == 1
    assert user.quota_used == 1

    job = AnalysisJobRepository.create_job(
        session=test_db_session,
        user_id=user.id,
        repo_url="https://github.com/owner/failing-repo",
        status="running",
    )
    assert job.status == "running"

    # Simulate an unhandled exception in pipeline worker
    try:
        raise RuntimeError("Sandboxed AST parsing failure: syntax corruption")
    except Exception as exc:
        # Repository updates status to failed in a single atomic transaction
        AnalysisJobRepository.update_job_status(
            session=test_db_session,
            job_id=job.id,
            status="failed",
            error_message=str(exc),
        )

    # Job status is failed
    test_db_session.refresh(job)
    assert job.status == "failed"
    assert "Sandboxed AST parsing failure" in job.error_message

    # Assert quota_used returns to its previous value (0)
    assert user.quota_used == initial_quota
    assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 0


def test_refund_quota_on_job_cancellation(test_db_session):
    """Confirm quota is also refunded if a running job transitions to cancelled."""
    user = UserModel(github_id=9003, github_username="cancel_user", email="cancel@test.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    # Charge quota
    BillingService.check_and_consume_quota(user, test_db_session)
    assert user.quota_used == 1

    job = AnalysisJobRepository.create_job(
        session=test_db_session,
        user_id=user.id,
        repo_url="https://github.com/owner/cancelled-repo",
        status="running",
    )

    # Cancel job
    AnalysisJobRepository.update_job_status(test_db_session, job.id, status="cancelled")
    test_db_session.refresh(job)
    assert job.status == "cancelled"
    assert user.quota_used == 0


# =========================================================================
# Part C: Quota Display & 5/5 Gating Tests
# =========================================================================

def test_quota_display_one_line_and_one_bar():
    """
    Replace the three ways of showing quota (badge, bar, "3/5 allotted (60% consumed)")
    with one line and one bar: "3 of 5 analyses used this month".
    """
    billing_status = {
        "tier": "free",
        "monthly_usage": 3,
        "monthly_quota": 5,
        "is_quota_exceeded": False,
    }
    user = UserModel(id=1, github_id=9004, github_username="display_user")
    html = dashboard_view(
        current_user=user,
        billing_status=billing_status,
        past_jobs=[],
    )

    # Assert one line and one bar format
    assert "3 of 5 analyses used this month" in html
    assert 'class="meter"' in html

    # Assert old repetitive patterns are gone
    assert "JOBS ALLOTTED" not in html
    assert "60% CONSUMED" not in html
    assert '<span class="badge badge-free">FREE TIER</span>' not in html


def test_quota_display_exhausted_five_of_five_disables_button():
    """
    When 5/5 is used, disable the Analyze button and show:
    "You've used all 5 analyses this month. Resets on {date}."
    If billing is enabled, also show a secondary Upgrade link.
    """
    billing_status = {
        "tier": "free",
        "monthly_usage": 5,
        "monthly_quota": 5,
        "is_quota_exceeded": True,
    }
    user = UserModel(id=1, github_id=9005, github_username="exhausted_user")

    with patch("app.ui.components.billing_enabled", return_value=True):
        html = dashboard_view(
            current_user=user,
            billing_status=billing_status,
            past_jobs=[],
        )

        assert "5 of 5 analyses used this month" in html
        assert "You've used all 5 analyses this month. Resets on " in html
        assert "disabled" in html
        assert "id=\"analyze-button\"" in html
        # Secondary upgrade link is shown
        assert "Upgrade" in html


def test_submitting_when_quota_exhausted_returns_403_or_flash_and_creates_no_job(client, test_db_session):
    """
    Test the 5/5 state: submitting returns a 403 or a flash message and creates no job.
    """
    user = UserModel(github_id=9006, github_username="five_user", email="five@test.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    # Fill up 5 quota slots
    for _ in range(5):
        BillingRepository.record_usage_event(test_db_session, user.id, event_type="repo_analysis")
    test_db_session.commit()
    assert user.quota_used == 5

    app.dependency_overrides[get_current_user_optional] = lambda: user
    app.dependency_overrides[get_db] = lambda: test_db_session

    try:
        with patch("app.services.ingestion.check_repo_size_preflight", return_value=10):
            # Test HTML form submission (flash message redirect)
            resp = client.post(
                "/analyses/submit",
                data={"repo_url": "https://github.com/owner/excess-repo"},
                follow_redirects=False,
            )

            # Submitting returns a 403 or a flash message (302 with error)
            assert resp.status_code in (403, 302)
            if resp.status_code == 302:
                loc = resp.headers["location"]
                assert "error=" in loc
                assert "You've+used+all+5+analyses+this+month" in loc

            # Test JSON client submission (403)
            resp_json = client.post(
                "/analyses/submit",
                data={"repo_url": "https://github.com/owner/excess-repo"},
                headers={"Accept": "application/json"},
                follow_redirects=False,
            )
            assert resp_json.status_code == 403
            assert "You've used all 5 analyses this month" in resp_json.json()["detail"]

            # Assert ZERO jobs were created
            jobs = AnalysisJobRepository.get_jobs_for_user(test_db_session, user.id)
            assert len(jobs) == 0

    finally:
        app.dependency_overrides.clear()


# =========================================================================
# Part D: Cold Start & /healthz Tests
# =========================================================================

def test_healthz_endpoint_status_and_no_auth(client):
    """GET /healthz returns {"status": "ok"} with no database call and no auth."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_base_template_has_cold_start_bar_and_script():
    """
    Base template includes full-width bar 'Waking up the server, this can take up to a minute…'
    and script monitoring /healthz response beyond 3 seconds.
    """
    billing_status = {"tier": "free", "monthly_usage": 0, "monthly_quota": 5}
    user = UserModel(id=1, github_id=9007, github_username="cold_user")
    html = dashboard_view(current_user=user, billing_status=billing_status, past_jobs=[])

    assert "cold-start-banner" in html
    assert "Waking up the server, this can take up to a minute…" in html
    assert "fetch('/healthz')" in html
    assert "3000" in html


def test_keepalive_doc_exists_and_has_four_lines():
    """Confirm docs/KEEPALIVE.md exists with 4 lines configuring cron-job.org."""
    doc_path = os.path.join("docs", "KEEPALIVE.md")
    assert os.path.isfile(doc_path)
    with open(doc_path, "r", encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    assert len(lines) == 4
    assert any("https://<app>/healthz" in line for line in lines)
    assert any("every 10 minutes" in line for line in lines)
    assert any("cron-job.org" in line for line in lines)


# =========================================================================
# Part E: Retry Quota Charging & Refund Correctness Tests (Parts B & C)
# =========================================================================

def test_retry_blocked_at_quota_limit_and_job_stays_failed(client, test_db_session):
    """A user at 5/5 with a failed job is blocked from retrying, quota stays 5, and job stays failed."""
    from app.api.dependencies import get_current_user, get_current_user_optional
    user = UserModel(github_id=9010, github_username="quota_user_5", email="q5@test.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    app.dependency_overrides[get_current_user_optional] = lambda: user
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: test_db_session

    try:
        # Create 5 usage events so user is at 5/5 quota
        for _ in range(5):
            BillingRepository.record_usage_event(test_db_session, user.id)
        assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 5

        # Create a failed job owned by user
        job = AnalysisJobRepository.create_job(
            session=test_db_session,
            user_id=user.id,
            repo_url="https://github.com/owner/failed-repo",
            status="failed",
            error_message="Original error",
        )
        assert job.status == "failed"

        # UI retry attempt (should redirect with flash error message, not reset job)
        resp_ui = client.post(f"/analyses/{job.id}/retry", follow_redirects=False)
        assert resp_ui.status_code == 302
        assert "error=" in resp_ui.headers["location"]
        assert "You've+used+all+5+analyses+this+month" in resp_ui.headers["location"]

        test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message == "Original error"
        assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 5

        # API retry attempt (should return 403, not reset job)
        resp_api = client.post(f"/api/analyses/{job.id}/retry")
        assert resp_api.status_code == 403
        assert "You've used all 5 analyses this month" in resp_api.json()["detail"]

        test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message == "Original error"
        assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 5
    finally:
        app.dependency_overrides.clear()


def test_retry_success_charges_quota(client, test_db_session):
    """A user at 3/5 retries a failed job; retry charges quota and usage becomes 4."""
    from app.api.dependencies import get_current_user, get_current_user_optional
    user = UserModel(github_id=9011, github_username="quota_user_3", email="q3@test.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    app.dependency_overrides[get_current_user_optional] = lambda: user
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: test_db_session

    try:
        # Create 3 usage events so user is at 3/5 quota
        for _ in range(3):
            BillingRepository.record_usage_event(test_db_session, user.id)
        assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 3

        # Create a failed job owned by user
        job = AnalysisJobRepository.create_job(
            session=test_db_session,
            user_id=user.id,
            repo_url="https://github.com/owner/retryable-repo",
            status="failed",
            error_message="Temporary failure",
        )
        assert job.status == "failed"

        # Retry job via UI
        resp = client.post(f"/analyses/{job.id}/retry", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == f"/progress/{job.id}"

        test_db_session.refresh(job)
        assert job.status == "pending"
        assert job.error_message is None
        assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 4
    finally:
        app.dependency_overrides.clear()


def test_failing_job_once_and_twice_idempotency(test_db_session):
    """Failing a job once changes usage by -1. Failing it twice still gives -1 in total."""
    user = UserModel(github_id=9012, github_username="fail_user", email="fail@test.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    # User consumes quota and creates job
    is_allowed, usage, limit, tier = BillingService.check_and_consume_quota(user, test_db_session)
    assert is_allowed is True
    assert usage == 1

    job = AnalysisJobRepository.create_job(
        session=test_db_session,
        user_id=user.id,
        repo_url="https://github.com/owner/fail-twice-repo",
        status="running",
    )

    # First failure -> changes usage by -1 (usage becomes 0)
    AnalysisJobRepository.update_job_status(test_db_session, job.id, status="failed", error_message="Crash 1")
    assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 0

    # Second failure on already failed job -> does NOT refund again, still -1 in total (usage stays 0)
    AnalysisJobRepository.update_job_status(test_db_session, job.id, status="failed", error_message="Crash 2")
    assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 0


def test_cancel_route_gives_exactly_minus_one(client, test_db_session):
    """The cancel route refunds exactly -1 and does not double-refund."""
    from app.api.dependencies import get_current_user_optional
    user = UserModel(github_id=9013, github_username="cancel_route_user", email="cancel_route@test.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    app.dependency_overrides[get_current_user_optional] = lambda: user
    app.dependency_overrides[get_db] = lambda: test_db_session

    try:
        # User has 2 jobs running (usage = 2)
        BillingService.check_and_consume_quota(user, test_db_session)
        job1 = AnalysisJobRepository.create_job(
            session=test_db_session,
            user_id=user.id,
            repo_url="https://github.com/owner/cancel-repo-1",
            status="running",
        )
        BillingService.check_and_consume_quota(user, test_db_session)
        job2 = AnalysisJobRepository.create_job(
            session=test_db_session,
            user_id=user.id,
            repo_url="https://github.com/owner/cancel-repo-2",
            status="running",
        )
        assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 2

        # Cancel job1 via route
        resp = client.post(f"/jobs/{job1.id}/cancel", headers={"accept": "application/json"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        # Quota must change by EXACTLY -1 (from 2 to 1, NOT 0)
        assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 1

        # Repeating cancel on already cancelled job does not refund again
        resp_again = client.post(f"/jobs/{job1.id}/cancel", headers={"accept": "application/json"})
        assert resp_again.status_code == 200
        assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 1
    finally:
        app.dependency_overrides.clear()


def test_failing_older_job_removes_older_job_event(test_db_session):
    """With two jobs from one user, failing the OLDER job removes the older job's event, asserted by job_id."""
    from app.models.db import UsageEventModel
    from sqlalchemy import select

    user = UserModel(github_id=9014, github_username="older_job_user", email="older@test.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    # 1. First (older) job submission
    BillingService.check_and_consume_quota(user, test_db_session)
    older_job = AnalysisJobRepository.create_job(
        session=test_db_session,
        user_id=user.id,
        repo_url="https://github.com/owner/older-repo",
        status="running",
    )

    # 2. Second (newer) job submission
    BillingService.check_and_consume_quota(user, test_db_session)
    newer_job = AnalysisJobRepository.create_job(
        session=test_db_session,
        user_id=user.id,
        repo_url="https://github.com/owner/newer-repo",
        status="running",
    )

    assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 2

    # Verify both jobs have linked events
    events = list(test_db_session.scalars(
        select(UsageEventModel).where(UsageEventModel.user_id == user.id).order_by(UsageEventModel.id.asc())
    ).all())
    assert len(events) == 2
    assert events[0].job_id == older_job.id
    assert events[1].job_id == newer_job.id

    # Fail the OLDER job
    AnalysisJobRepository.update_job_status(test_db_session, older_job.id, status="failed")

    # Usage must now be 1
    assert BillingRepository.get_monthly_usage_count(test_db_session, user.id) == 1

    # Assert by job_id that the remaining event belongs to newer_job, and older_job's event was removed
    remaining_events = list(test_db_session.scalars(
        select(UsageEventModel).where(UsageEventModel.user_id == user.id)
    ).all())
    assert len(remaining_events) == 1
    assert remaining_events[0].job_id == newer_job.id
    assert not any(e.job_id == older_job.id for e in remaining_events)
