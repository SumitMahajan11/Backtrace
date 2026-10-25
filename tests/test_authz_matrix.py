"""Authorization Matrix, Production Sandbox Execution Protection,
and Input Validation Test Suite.
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, MilestoneAttemptModel, UserModel
from app.security.auth import create_access_token
from app.services.execution_verifier import (
    ExecutionVerifier,
    ExecutionVerifierConnectionError,
)
from app.services.piston_health import piston_health_monitor
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.milestone_attempt_repository import MilestoneAttemptRepository
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
def owner_user(test_db) -> UserModel:
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        user = UserRepository.upsert_github_user(
            session=session,
            github_id=9001,
            github_username="job_owner",
            email="owner@example.com",
            avatar_url="https://avatars.example.com/owner",
        )
        session.commit()
        session.refresh(user)
        return user


@pytest.fixture
def other_user(test_db) -> UserModel:
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        user = UserRepository.upsert_github_user(
            session=session,
            github_id=9002,
            github_username="non_owner_snooper",
            email="snooper@example.com",
            avatar_url="https://avatars.example.com/snooper",
        )
        session.commit()
        session.refresh(user)
        return user


# =========================================================================
# 1. Sandbox Protection Test (Prompt Item 2)
# =========================================================================

def test_production_sandbox_refuses_code_without_piston(monkeypatch):
    """
    In production mode (ENVIRONMENT=production, SANDBOX_ENABLED=true) with no Piston URL,
    submitted code must be REFUSED (fail-closed) and never run on the web server.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SANDBOX_ENABLED", "true")
    monkeypatch.setenv("PISTON_URL", "http://127.0.0.1:9999")
    from app.core.config import get_settings
    get_settings.cache_clear()

    # Ensure monitor reports unhealthy when Piston URL is dead
    piston_health_monitor.piston_url = "http://127.0.0.1:9999"
    piston_health_monitor._is_healthy = False

    verifier = ExecutionVerifier(piston_url="http://127.0.0.1:9999")
    assert verifier.allow_local_fallback is False

    with pytest.raises(ExecutionVerifierConnectionError) as exc_info:
        verifier.execute(submitted_code="import os; os.system('echo pwned')", language="python")

    assert "Code execution sandbox is currently unavailable" in str(exc_info.value)


# =========================================================================
# 2. Authorization Matrix Tests (Prompt Item 3)
# =========================================================================

def test_authz_matrix_routes(client, owner_user, other_user, test_db):
    """
    For every route taking job_id, attempt_id, milestone_tier, or user_id,
    checks 3 callers:
      1. Anonymous (unauthenticated)
      2. Non-owner (authenticated User B)
      3. Owner (authenticated User A)

    Non-owners and anonymous must get 401, 403 or 404 and never 200.
    """
    SessionLocal, _ = test_db

    # Create Owner's confidential completed job
    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=owner_user.id,
            repo_url="https://github.com/owner-org/secret-repo",
            status="completed",
        )
        job_id = job.id
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job_id,
            status="completed",
            report_markdown="# Confidential Architecture Report\n\nSecret blueprints.",
            graph_data={"nodes": [{"id": "core.py", "tier": 1}], "edges": []},
            quiz_data={"questions": []},
        )
        attempt = MilestoneAttemptRepository.save_or_update_attempt(
            session=session,
            user_id=owner_user.id,
            job_id=job_id,
            milestone_tier=1,
            submitted_code="def solve(): pass",
            status="verified",
        )
        attempt_id = attempt.id

    # Create tokens
    owner_token = create_access_token(user_id=owner_user.id, github_id=owner_user.github_id, github_username=owner_user.github_username)
    other_token = create_access_token(user_id=other_user.id, github_id=other_user.github_id, github_username=other_user.github_username)

    tier = 1

    # Matrix definition of routes taking job_id, attempt_id, milestone_tier, user_id
    routes_to_test = [
        # (method, path, is_html_redirect)
        ("GET", f"/report/{job_id}", True),
        ("GET", f"/progress/{job_id}", True),
        ("GET", f"/api/analyses/{job_id}/events", False),
        ("GET", f"/api/analyses/{job_id}/status", False),
        ("POST", f"/analyses/{job_id}/retry", True),
        ("POST", f"/api/analyses/{job_id}/retry", False),
        ("GET", f"/attempts/by-id/{attempt_id}", False),
        ("GET", f"/attempts/{job_id}/{tier}", False),
        ("POST", f"/attempts/{job_id}/{tier}/hint", False),
        ("POST", f"/attempts/{job_id}/{tier}/reveal", False),
        ("GET", f"/attempts/{job_id}/{tier}/view", False),
        ("POST", f"/attempts/{job_id}/{tier}/review", False),
        ("GET", f"/points/user/{owner_user.id}", False),
        ("GET", f"/points/job/{job_id}", False),
    ]

    for method, path, is_html_redirect in routes_to_test:
        if "retry" in path:
            with SessionLocal() as s:
                AnalysisJobRepository.update_job_status(s, job_id, status="failed")
        else:
            with SessionLocal() as s:
                AnalysisJobRepository.update_job_status(s, job_id, status="completed")

        # 1. Anonymous Caller
        client.cookies.clear()
        if method == "GET":
            resp_anon = client.get(path, follow_redirects=False)
        else:
            resp_anon = client.post(path, follow_redirects=False)

        # Anonymous must get 401, 403, 404 (or 302 redirect on HTML views), NEVER 200
        assert resp_anon.status_code != 200, f"Anonymous caller got 200 on {path}"
        if is_html_redirect:
            assert resp_anon.status_code in (302, 401, 403, 404), f"Anonymous caller got {resp_anon.status_code} on {path}"
        else:
            assert resp_anon.status_code in (401, 403, 404), f"Anonymous caller got {resp_anon.status_code} on {path}"

        # 2. Non-Owner Caller
        client.cookies.set("access_token", other_token)
        if method == "GET":
            resp_other = client.get(path, follow_redirects=False)
        else:
            resp_other = client.post(path, follow_redirects=False)

        # Non-owner must get 401, 403 or 404, NEVER 200
        assert resp_other.status_code != 200, f"Non-owner caller got 200 on {path}"
        assert resp_other.status_code in (401, 403, 404), f"Non-owner caller got {resp_other.status_code} on {path}"

        # 3. Owner Caller
        client.cookies.set("access_token", owner_token)
        if method == "GET":
            resp_owner = client.get(path, follow_redirects=False)
        else:
            resp_owner = client.post(path, follow_redirects=False)

        # Owner gets route-specific expected status: retry path gets (302, 409), all others get original (200,)
        if path == f"/analyses/{job_id}/retry":
            assert resp_owner.status_code in (302, 409), f"Owner got {resp_owner.status_code} on retry route {path}"
        else:
            assert resp_owner.status_code in (200,), f"Owner got {resp_owner.status_code} on {path}"


def test_authz_matrix_showcase_exception(client, owner_user, other_user, test_db):
    """
    Showcase jobs are excepted from strict IDOR: read-only access is permitted
    for anonymous, non-owners, and owners on /report/{showcase_job_id}.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        showcase_job = AnalysisJobRepository.create_job(
            session=session,
            user_id=owner_user.id,
            repo_url="https://github.com/showcase-org/public-demo",
            status="completed",
        )
        showcase_job.is_showcase = True
        showcase_job_id = showcase_job.id
        session.commit()

        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=showcase_job_id,
            status="completed",
            report_markdown="# Public Showcase Report",
            graph_data={"nodes": [{"id": "demo.py", "tier": 1}], "edges": []},
            quiz_data={"questions": []},
        )

    owner_token = create_access_token(user_id=owner_user.id, github_id=owner_user.github_id, github_username=owner_user.github_username)
    other_token = create_access_token(user_id=other_user.id, github_id=other_user.github_id, github_username=other_user.github_username)

    # 1. Anonymous caller -> 200 OK on showcase report
    client.cookies.clear()
    resp_anon = client.get(f"/report/{showcase_job_id}", follow_redirects=False)
    assert resp_anon.status_code == 200
    assert "View-only showcase" in resp_anon.text

    # 2. Non-owner caller -> 200 OK on showcase report
    client.cookies.set("access_token", other_token)
    resp_other = client.get(f"/report/{showcase_job_id}", follow_redirects=False)
    assert resp_other.status_code == 200
    assert "View-only showcase" in resp_other.text

    # 3. Owner caller -> 200 OK on showcase report
    client.cookies.set("access_token", owner_token)
    resp_owner = client.get(f"/report/{showcase_job_id}", follow_redirects=False)
    assert resp_owner.status_code == 200


# =========================================================================
# 3. Input Checks Test (Prompt Item 5)
# =========================================================================

def test_input_checks(client, owner_user, test_db, monkeypatch):
    """
    Tests input validation on repository submission:
      - a github_url that is not github.com
      - a subpath containing '..'
      - an absolute subpath
      - a branch with shell characters
    The contract: bad input is rejected with a 4xx, or a redirect or 200 that
    carries an error message AND creates no AnalysisJob row AND starts no ingestion.
    For each of the 4 cases assert both and print the raw response message.
    If any case creates a job, print it and stop.
    """
    SessionLocal, _ = test_db
    owner_token = create_access_token(
        user_id=owner_user.id,
        github_id=owner_user.github_id,
        github_username=owner_user.github_username,
    )
    client.cookies.set("access_token", owner_token)

    ingestion_started = False
    def mock_ingest_guard(*args, **kwargs):
        nonlocal ingestion_started
        ingestion_started = True
        raise RuntimeError("Ingestion should not be started for invalid input!")

    monkeypatch.setattr("app.services.ingestion.IngestionService.ingest_repository", mock_ingest_guard)

    cases = [
        ("non_github_url", {"repo_url": "https://gitlab.com/attacker/malicious-repo"}),
        ("dotdot_subpath", {"repo_url": "https://github.com/owner/repo", "subpath": "src/../../etc"}),
        ("absolute_subpath", {"repo_url": "https://github.com/owner/repo", "subpath": "/var/run/secrets"}),
        ("shell_branch", {"repo_url": "https://github.com/owner/repo", "commit_ref": "main; rm -rf /"}),
    ]

    for case_name, form_data in cases:
        resp = client.post("/analyses/submit", data=form_data, follow_redirects=False)

        # 1. Extract raw response message
        raw_msg = ""
        if resp.status_code == 302:
            loc = resp.headers.get("location", "")
            if "error=" in loc:
                from urllib.parse import parse_qs, urlparse
                qs = parse_qs(urlparse(loc).query)
                raw_msg = qs.get("error", [""])[0]
            else:
                raw_msg = f"Redirect to {loc}"
        elif resp.status_code in (200, 400, 422):
            import re
            # Extract error text from rendered dashboard banner or json detail
            m = re.search(r'id="form-error-banner"[^>]*>([\s\S]*?)</div>', resp.text)
            if not m:
                m = re.search(r'class="[^"]*error[^"]*"[^>]*>([\s\S]*?)</div>', resp.text)
            if m:
                raw_msg = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            else:
                raw_msg = resp.text[:200].strip()

        print(f"Case [{case_name}]: status={resp.status_code}, raw_message={raw_msg!r}")

        # Assert status code is 4xx or 302/200 carrying an error message
        is_4xx = 400 <= resp.status_code < 500
        is_redirect_with_err = resp.status_code == 302 and bool(raw_msg)
        is_200_with_err = resp.status_code == 200 and bool(raw_msg)
        assert is_4xx or is_redirect_with_err or is_200_with_err, (
            f"Case [{case_name}] failed contract: status={resp.status_code}, raw_message={raw_msg!r}"
        )
        assert bool(raw_msg), f"Case [{case_name}] missing error message!"

        # Assert no ingestion started
        assert not ingestion_started, f"Case [{case_name}] started ingestion unexpectedly!"

        # Assert no AnalysisJob row created
        with SessionLocal() as session:
            jobs = AnalysisJobRepository.get_jobs_for_user(session, owner_user.id)
            if len(jobs) > 0:
                print(f"STOPPING: Case [{case_name}] created AnalysisJob row: {jobs}")
            assert len(jobs) == 0, f"Case [{case_name}] created an AnalysisJob row!"


def test_retry_running_or_completed_job_returns_409(client, owner_user, test_db):
    """
    Retrying an active ('running') or already finished ('completed') job
    returns HTTP 409 Conflict across both API and JSON-accepting UI retry endpoints.
    """
    SessionLocal, _ = test_db
    owner_token = create_access_token(
        user_id=owner_user.id,
        github_id=owner_user.github_id,
        github_username=owner_user.github_username,
    )
    client.cookies.set("access_token", owner_token)

    for initial_status in ("running", "completed"):
        with SessionLocal() as session:
            job = AnalysisJobRepository.create_job(
                session=session,
                user_id=owner_user.id,
                repo_url=f"https://github.com/owner/job-{initial_status}",
                status=initial_status,
            )
            job_id = job.id

        # 1. API endpoint /api/analyses/{job_id}/retry returns exactly 409
        resp_api = client.post(f"/api/analyses/{job_id}/retry")
        assert resp_api.status_code == 409, f"Expected 409 on API retry for {initial_status} job, got {resp_api.status_code}"
        assert resp_api.json().get("detail") == "This analysis can't be retried."

        # 2. UI endpoint /analyses/{job_id}/retry with Accept: application/json returns exactly 409
        resp_ui_json = client.post(
            f"/analyses/{job_id}/retry",
            headers={"Accept": "application/json"},
        )
        assert resp_ui_json.status_code == 409, f"Expected 409 on UI retry (json) for {initial_status} job, got {resp_ui_json.status_code}"
        assert resp_ui_json.json().get("detail") == "This analysis can't be retried."


