"""Tests for Step 5: Progress Rebuild, Phase Mapping, Cancel Endpoint, and Purged Failure Leaks."""

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import UserModel
from app.security.auth import create_access_token
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.billing_repository import BillingRepository
from app.storage.user_repository import UserRepository
from app.ui.components import map_stage_to_phase, map_failure_reason


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


# -----------------------------------------------------------------------------
# Test 1: Stage to Phase mapping for all 11 stages (11 assertions)
# -----------------------------------------------------------------------------
def test_map_stage_to_phase_11_stages():
    """Verify mapping function stage -> phase for all 11 stages (11 distinct assertions)."""
    assert map_stage_to_phase("stage_0") == {"phase_index": 1, "phase_name": "Get the code"}
    assert map_stage_to_phase("stage_1") == {"phase_index": 1, "phase_name": "Get the code"}
    assert map_stage_to_phase("stage_2") == {"phase_index": 2, "phase_name": "Read the files"}
    assert map_stage_to_phase("stage_3") == {"phase_index": 2, "phase_name": "Read the files"}
    assert map_stage_to_phase("stage_4") == {"phase_index": 2, "phase_name": "Read the files"}
    assert map_stage_to_phase("stage_5") == {"phase_index": 3, "phase_name": "Map how they connect"}
    assert map_stage_to_phase("stage_6") == {"phase_index": 3, "phase_name": "Map how they connect"}
    assert map_stage_to_phase("stage_7") == {"phase_index": 4, "phase_name": "Build your guide"}
    assert map_stage_to_phase("stage_8") == {"phase_index": 4, "phase_name": "Build your guide"}
    assert map_stage_to_phase("stage_9") == {"phase_index": 4, "phase_name": "Build your guide"}
    assert map_stage_to_phase("stage_10") == {"phase_index": 4, "phase_name": "Build your guide"}


# -----------------------------------------------------------------------------
# Test 2: Cancel route changes status and refunds quota
# -----------------------------------------------------------------------------
def test_cancel_route_changes_status_and_refunds_quota(client, create_user, test_db):
    """POST /jobs/{id}/cancel sets status=cancelled if queued or running, and refunds quota."""
    SessionLocal, _ = test_db
    user = create_user(github_id=98701, username="canceller")

    with SessionLocal() as session:
        # Simulate user consuming 1 quota slot for this analysis job
        BillingRepository.record_usage_event(session, user_id=user.id, event_type="repo_analysis")
        session.commit()
        usage_before = BillingRepository.get_monthly_usage_count(session, user.id)
        assert usage_before == 1

        # Create running analysis job
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/expressjs/express",
            status="running",
        )
        job_id = job.id

    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    # Call POST /jobs/{id}/cancel
    resp = client.post(f"/jobs/{job_id}/cancel", headers={"accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "cancelled"

    # Verify status changed in database and quota was refunded
    with SessionLocal() as session:
        updated_job = AnalysisJobRepository.get_job_by_id(session, job_id)
        assert updated_job.status == "cancelled"
        usage_after = BillingRepository.get_monthly_usage_count(session, user.id)
        assert usage_after == 0


def test_cancel_route_form_submission_redirects_and_renders_cancelled_card(client, create_user, test_db):
    """POST /jobs/{id}/cancel via HTML form redirects back to progress view showing cancelled state."""
    SessionLocal, _ = test_db
    user = create_user(github_id=98702, username="canceller_ui")

    with SessionLocal() as session:
        BillingRepository.record_usage_event(session, user_id=user.id, event_type="repo_analysis")
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/gin-gonic/gin",
            status="pending",
        )
        job_id = job.id

    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    resp = client.post(f"/jobs/{job_id}/cancel", follow_redirects=True)
    assert resp.status_code == 200
    html = resp.text
    assert "Analysis cancelled" in html
    assert "Back to dashboard" in html


# -----------------------------------------------------------------------------
# Test 3: Failed job page contains none of: "docket", "tenant", "Traceback", "token=abc"
# -----------------------------------------------------------------------------
def test_failed_job_page_contains_no_docket_tenant_traceback(client, create_user, test_db):
    """Failed job page renders mapped user-friendly error and contains none of: docket, tenant, Traceback, token=abc."""
    SessionLocal, _ = test_db
    user = create_user(github_id=98703, username="failed_user")

    raw_internal_error = (
        "Traceback (most recent call last):\n"
        "  File '/app/security/tenant_validator.py', line 45, in validate_tenant\n"
        "    raise TenantSecurityException('docket security check failed: clone unauthorized 403 token=abc')\n"
        "fatal: could not resolve host or repository is private"
    )

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/private-org/secret-repo",
            status="failed",
            error_message=raw_internal_error,
        )
        job_id = job.id

    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    resp = client.get(f"/progress/{job_id}")
    assert resp.status_code == 200
    html = resp.text

    # Plain mapped message appears
    assert "Analysis failed" in html
    assert "We couldn't access this repository (it may be private or the link is wrong)" in html
    assert "Retry" in html
    assert "Back to dashboard" in html

    # Strictly verify purged terms (case-insensitive)
    lower_html = html.lower()
    assert "docket" not in lower_html
    assert "tenant" not in lower_html
    assert "traceback" not in lower_html
    assert "token=abc" not in lower_html


# -----------------------------------------------------------------------------
# Test 4: Completed job renders "Report ready" card with 3 real numbers and no auto-redirect
# -----------------------------------------------------------------------------
def test_completed_job_renders_report_ready_card_no_auto_redirect(client, create_user, test_db):
    """Completed job renders Report ready card with 3 real numbers and primary Start learning button."""
    SessionLocal, _ = test_db
    user = create_user(github_id=98704, username="learner")

    markdown = """# Architectural Reverse-Engineering Report: `fastapi`
*Synthesized at: 2026-10-23 20:00:00 UTC*

## 1. Executive Architecture Overview
- **Primary Language**: `Python`
- **Total Analyzed Files**: `85`
- **Domain Categories**: `7`
- **Entry Point Files**: `main.py, app/api.py`
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/tiangolo/fastapi",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=markdown,
            graph_data={"nodes": [{"id": f"n_{i}"} for i in range(85)]},
            execution_time_seconds=14.2,
        )
        job_id = job.id

    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    resp = client.get(f"/progress/{job_id}", follow_redirects=False)
    # Silent redirect is removed -> status 200
    assert resp.status_code == 200
    html = resp.text

    assert "Report ready" in html
    assert "85" in html  # files analyzed
    assert "7" in html   # modules
    assert "2" in html   # entry points
    assert "Start learning" in html
    assert f"/report/{job_id}" in html


# -----------------------------------------------------------------------------
# Test 5: IDOR security check on cancel route
# -----------------------------------------------------------------------------
def test_cancel_route_idor_protection(client, create_user, test_db):
    """User B cannot cancel User A's job."""
    SessionLocal, _ = test_db
    user_a = create_user(github_id=98705, username="user_a")
    user_b = create_user(github_id=98706, username="user_b")

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user_a.id,
            repo_url="https://github.com/gin-gonic/gin",
            status="running",
        )
        job_id = job.id

    # Authenticate as User B
    token_b = create_access_token(user_id=user_b.id, github_id=user_b.github_id, github_username=user_b.github_username)
    client.cookies.set("access_token", token_b)

    resp = client.post(f"/jobs/{job_id}/cancel")
    assert resp.status_code == 403
    assert "Access forbidden" in resp.text


# -----------------------------------------------------------------------------
# Test 6: Cancel mid-run with patched slow stage keeps cancelled status and refunds exactly 1 quota
# -----------------------------------------------------------------------------
def test_cancel_mid_run_with_slow_stage_keeps_cancelled_status_and_refunds(client, create_user, test_db):
    """Cancel mid-run with a patched slow stage: final status stays 'cancelled' and usage changes by exactly -1."""
    import threading

    SessionLocal, _ = test_db
    user = create_user(github_id=98707, username="slow_runner")

    with SessionLocal() as session:
        # User consumes 1 quota slot
        BillingRepository.record_usage_event(session, user_id=user.id, event_type="repo_analysis")
        session.commit()
        usage_before = BillingRepository.get_monthly_usage_count(session, user.id)
        assert usage_before == 1

        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/org/slow-repo",
            status="running",
        )
        job_id = job.id

    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    # Simulate worker running in background thread with a slow stage that cooperatively checks cancellation
    stage_entered = threading.Event()
    finish_worker = threading.Event()

    def worker_target():
        # First cooperative check before slow stage
        with SessionLocal() as s1:
            j = AnalysisJobRepository.get_job_by_id(s1, job_id)
            if j and j.status == "cancelled":
                return
        stage_entered.set()
        # Wait until cancel has been called or timeout
        finish_worker.wait(timeout=5.0)

        # Cooperative check after slow stage
        with SessionLocal() as s2:
            j = AnalysisJobRepository.get_job_by_id(s2, job_id)
            if j and j.status == "cancelled":
                return

        # Even if a slow worker attempts to update status or save result:
        with SessionLocal() as s3:
            AnalysisJobRepository.update_job_status(s3, job_id, status="completed")
            AnalysisJobRepository.save_job_result(
                s3, job_id, markdown_output="# Done", graph_output_json="{}", quiz_output_json="{}", execution_time_seconds=1.0
            )

    worker_thread = threading.Thread(target=worker_target, daemon=True)
    worker_thread.start()

    # Wait for worker to enter stage
    assert stage_entered.wait(timeout=3.0)

    # Cancel the job while worker is in the middle of slow stage
    resp = client.post(f"/jobs/{job_id}/cancel", headers={"accept": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    # Now let the worker resume and try to finish
    finish_worker.set()
    worker_thread.join(timeout=3.0)

    with SessionLocal() as session:
        final_job = AnalysisJobRepository.get_job_by_id(session, job_id)
        assert final_job.status == "cancelled"

        # Attempt explicit post-cancel writes from finished worker to verify DB guards
        AnalysisJobRepository.update_job_status(session, job_id, status="completed")
        AnalysisJobRepository.save_job_result(
            session, job_id, markdown_output="# Done", graph_output_json="{}", quiz_output_json="{}", execution_time_seconds=1.0
        )
        session.commit()

        final_job_after = AnalysisJobRepository.get_job_by_id(session, job_id)
        assert final_job_after.status == "cancelled"

        usage_after = BillingRepository.get_monthly_usage_count(session, user.id)
        # Usage changed by exactly -1 (from 1 down to 0)
        assert usage_after - usage_before == -1
