"""Unit, Integration, Concurrency, and IDOR Tests for Points Engine (Prompt 23)."""

import os
import threading
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user, get_db
from app.core.config import get_settings
from app.db.session import Base, init_db
from app.main import app
from app.models.db import (
    AnalysisJobModel,
    MilestoneAttemptModel,
    PointsLedgerModel,
    UserModel,
    utc_now,
)
from app.services.points_engine import PointsEngine


# Set up isolated in-memory test database with StaticPool
@pytest.fixture(scope="module")
def test_db_session_factory():
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(target_engine=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    return TestingSessionLocal


@pytest.fixture
def db_session(test_db_session_factory):
    session = test_db_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_users(db_session):
    # Create User A
    user_a = db_session.query(UserModel).filter_by(github_id=9001).first()
    if not user_a:
        user_a = UserModel(
            github_id=9001,
            github_username="alice_dev",
            email="alice@example.com",
            is_admin=False,
        )
        db_session.add(user_a)

    # Create User B
    user_b = db_session.query(UserModel).filter_by(github_id=9002).first()
    if not user_b:
        user_b = UserModel(
            github_id=9002,
            github_username="bob_hacker",
            email="bob@example.com",
            is_admin=False,
        )
        db_session.add(user_b)

    db_session.commit()
    db_session.refresh(user_a)
    db_session.refresh(user_b)
    return user_a, user_b


@pytest.fixture
def test_job_qualifying(db_session, test_users):
    user_a, _ = test_users
    job = AnalysisJobModel(
        user_id=user_a.id,
        repo_name="psf/requests",
        github_url="https://github.com/psf/requests",
        status="completed",
        run_id="run_qualifying_123",
        markdown_output="# Architectural Report\n- **Total Analyzed Files**: `12`\n",
        graph_output_json="""{
            "repo_name": "psf/requests",
            "total_files": 12,
            "total_loc": 2500,
            "architecture_overview": {
                "total_files": 12,
                "total_loc": 2500,
                "total_domains": 4,
                "primary_language": "python"
            },
            "milestones": [
                {"tier": 1, "title": "Models", "files": ["requests/models.py"]},
                {"tier": 2, "title": "Sessions", "files": ["requests/sessions.py"]},
                {"tier": 3, "title": "Adapters", "files": ["requests/adapters.py"]},
                {"tier": 4, "title": "API", "files": ["requests/api.py"]}
            ]
        }""",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def test_job_low_complexity(db_session, test_users):
    user_a, _ = test_users
    job = AnalysisJobModel(
        user_id=user_a.id,
        repo_name="tiny/toy-repo",
        github_url="https://github.com/tiny/toy-repo",
        status="completed",
        run_id="run_tiny_456",
        markdown_output="# Architectural Report\n- **Total Analyzed Files**: `2`\n",
        graph_output_json="""{
            "repo_name": "tiny/toy-repo",
            "total_files": 2,
            "total_loc": 45,
            "architecture_overview": {
                "total_files": 2,
                "total_loc": 45,
                "total_domains": 1,
                "primary_language": "python"
            },
            "milestones": [
                {"tier": 1, "title": "Core", "files": ["main.py", "utils.py"]}
            ]
        }""",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def test_points_config_constants():
    """Verify locked points settings in app/core/config.py."""
    settings = get_settings()
    assert settings.POINTS_FIRST_SOLVE_ONLY is True
    assert settings.POINTS_BASE_VALUE == 50
    assert settings.POINTS_HINT_1_MULTIPLIER == 0.50
    assert settings.POINTS_HINT_2_MULTIPLIER == 0.25
    assert settings.POINTS_SOLUTION_REVEALED_MULTIPLIER == 0.0
    assert settings.POINTS_MIN_REPO_FILES == 5
    assert settings.POINTS_MIN_REPO_LOC == 150
    assert settings.POINTS_EXPIRY_DAYS == 180


def test_four_solve_states(db_session, test_users, test_job_qualifying):
    """
    Verify the 4 milestone submission states:
    (a) first solve, no hints -> 50 points (full)
    (b) different milestone, hint 1 -> 25 points (50%)
    (c) different milestone, hint 2 -> 12 points (25%)
    (d) different milestone, implementation revealed -> 0 points
    """
    user_a, _ = test_users
    job = test_job_qualifying

    # (a) Milestone 1: First solve, no hints
    attempt_1 = MilestoneAttemptModel(
        user_id=user_a.id,
        job_id=job.id,
        milestone_tier=1,
        submitted_code="class RequestEncoding: pass",
        status="structurally_verified",
        hint_level_revealed=0,
        implementation_revealed=False,
    )
    db_session.add(attempt_1)
    db_session.commit()

    res_1 = PointsEngine.award_points_for_milestone(db_session, user_a.id, job, 1, attempt_1)
    assert res_1.points_awarded == 50
    assert res_1.multiplier_applied == 1.0
    assert res_1.reason == "milestone_solved_no_hints"
    assert res_1.ledger_entry is not None
    assert res_1.ledger_entry.points_awarded == 50

    # (b) Milestone 2: Solved after Hint 1
    attempt_2 = MilestoneAttemptModel(
        user_id=user_a.id,
        job_id=job.id,
        milestone_tier=2,
        submitted_code="class Session: pass",
        status="structurally_verified",
        hint_level_revealed=1,
        implementation_revealed=False,
    )
    db_session.add(attempt_2)
    db_session.commit()

    res_2 = PointsEngine.award_points_for_milestone(db_session, user_a.id, job, 2, attempt_2)
    assert res_2.points_awarded == 25
    assert res_2.multiplier_applied == 0.50
    assert res_2.reason == "milestone_solved_hint_1"
    assert res_2.ledger_entry.points_awarded == 25

    # (c) Milestone 3: Solved after Hint 2
    attempt_3 = MilestoneAttemptModel(
        user_id=user_a.id,
        job_id=job.id,
        milestone_tier=3,
        submitted_code="class HTTPAdapter: pass",
        status="structurally_verified",
        hint_level_revealed=2,
        implementation_revealed=False,
    )
    db_session.add(attempt_3)
    db_session.commit()

    res_3 = PointsEngine.award_points_for_milestone(db_session, user_a.id, job, 3, attempt_3)
    assert res_3.points_awarded == 12
    assert res_3.multiplier_applied == 0.25
    assert res_3.reason == "milestone_solved_hint_2"
    assert res_3.ledger_entry.points_awarded == 12

    # (d) Milestone 4: Implementation revealed then solved
    attempt_4 = MilestoneAttemptModel(
        user_id=user_a.id,
        job_id=job.id,
        milestone_tier=4,
        submitted_code="def get(): pass",
        status="structurally_verified",
        hint_level_revealed=2,
        implementation_revealed=True,
    )
    db_session.add(attempt_4)
    db_session.commit()

    res_4 = PointsEngine.award_points_for_milestone(db_session, user_a.id, job, 4, attempt_4)
    assert res_4.points_awarded == 0
    assert res_4.multiplier_applied == 0.0
    assert res_4.reason == "solution_revealed"
    assert res_4.ledger_entry.points_awarded == 0

    # Check total balance for user A = 50 + 25 + 12 + 0 = 87
    current_balance = PointsEngine.get_user_points_balance(db_session, user_a.id)
    assert current_balance == 87


def test_first_solve_only_enforcement(db_session, test_users, test_job_qualifying):
    """Submitting the same already-solved milestone awards 0 additional points."""
    user_a, _ = test_users
    job = test_job_qualifying

    # Ensure Milestone 1 is already awarded
    attempt_1 = db_session.query(MilestoneAttemptModel).filter_by(
        user_id=user_a.id, job_id=job.id, milestone_tier=1
    ).first()
    if not attempt_1:
        attempt_1 = MilestoneAttemptModel(
            user_id=user_a.id,
            job_id=job.id,
            milestone_tier=1,
            submitted_code="class RequestEncoding: pass",
            status="structurally_verified",
            hint_level_revealed=0,
            implementation_revealed=False,
        )
        db_session.add(attempt_1)
        db_session.commit()
        PointsEngine.award_points_for_milestone(db_session, user_a.id, job, 1, attempt_1)

    initial_balance = PointsEngine.get_user_points_balance(db_session, user_a.id)

    # Re-submit tier 1
    res = PointsEngine.award_points_for_milestone(db_session, user_a.id, job, 1, attempt_1)
    assert res.points_awarded == 0
    assert res.multiplier_applied == 0.0
    assert res.reason == "first_solve_already_awarded"

    # Verify balance has not increased
    current_balance = PointsEngine.get_user_points_balance(db_session, user_a.id)
    assert current_balance == initial_balance


def test_complexity_floor_enforcement(db_session, test_users, test_job_low_complexity):
    """Repo below 5 files / 150 LOC awards 0 points regardless of hint state."""
    user_a, _ = test_users
    job = test_job_low_complexity

    attempt = MilestoneAttemptModel(
        user_id=user_a.id,
        job_id=job.id,
        milestone_tier=1,
        submitted_code="print('tiny')",
        status="structurally_verified",
        hint_level_revealed=0,
        implementation_revealed=False,
    )
    db_session.add(attempt)
    db_session.commit()

    res = PointsEngine.award_points_for_milestone(db_session, user_a.id, job, 1, attempt)
    assert res.points_awarded == 0
    assert res.multiplier_applied == 0.0
    assert res.reason == "below_complexity_floor"


def test_concurrency_race_condition_protection(test_db_session_factory, test_users):
    """Two simultaneous submissions on a fresh milestone award points exactly once."""
    session = test_db_session_factory()
    user_a = session.query(UserModel).filter_by(github_id=9001).first()

    # Create a fresh job for concurrency testing
    concurrent_job = AnalysisJobModel(
        user_id=user_a.id,
        repo_name="pallets/flask",
        github_url="https://github.com/pallets/flask",
        status="completed",
        run_id="run_concurrent_789",
        graph_output_json="""{
            "total_files": 15,
            "total_loc": 3500,
            "architecture_overview": {"total_files": 15, "total_loc": 3500}
        }""",
    )
    session.add(concurrent_job)
    session.commit()
    session.refresh(concurrent_job)

    attempt = MilestoneAttemptModel(
        user_id=user_a.id,
        job_id=concurrent_job.id,
        milestone_tier=1,
        submitted_code="class Flask: pass",
        status="structurally_verified",
        hint_level_revealed=0,
        implementation_revealed=False,
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)

    user_id_val = user_a.id
    job_id_val = concurrent_job.id

    results = []

    def submit_worker():
        worker_session = test_db_session_factory()
        try:
            worker_job = worker_session.get(AnalysisJobModel, job_id_val)
            worker_attempt = worker_session.query(MilestoneAttemptModel).filter_by(
                user_id=user_id_val, job_id=job_id_val, milestone_tier=1
            ).first()
            res = PointsEngine.award_points_for_milestone(
                worker_session, user_id_val, worker_job, 1, worker_attempt
            )
            results.append(res)
        finally:
            worker_session.close()

    t1 = threading.Thread(target=submit_worker)
    t2 = threading.Thread(target=submit_worker)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    session.close()

    # Verify that exactly one thread won the first-solve award (50 pts) and the other was awarded 0
    awarded_points = [r.points_awarded for r in results]
    assert sorted(awarded_points) == [0, 50]

    # Verify total positive awards in ledger for this job & tier is exactly 1
    verify_session = test_db_session_factory()
    ledger_entries = verify_session.query(PointsLedgerModel).filter_by(
        user_id=user_id_val, job_id=job_id_val, milestone_tier=1
    ).all()
    positive_entries = [e for e in ledger_entries if e.points_awarded > 0]
    assert len(positive_entries) == 1
    assert positive_entries[0].points_awarded == 50
    verify_session.close()


def test_points_rolling_expiration(db_session, test_users):
    """Points older than 180 days expire from active balance but remain in append-only ledger."""
    user_a, _ = test_users

    # Add an expired ledger entry from 200 days ago
    past_date = utc_now() - timedelta(days=200)
    expired_entry = PointsLedgerModel(
        user_id=user_a.id,
        job_id=1,
        milestone_tier=99,
        points_awarded=100,
        multiplier_applied=1.0,
        reason="old_milestone_solved",
        created_at=past_date,
    )
    db_session.add(expired_entry)
    db_session.commit()

    # Active balance should NOT include the 100 expired points
    active_balance = PointsEngine.get_user_points_balance(db_session, user_a.id)
    expired_points = PointsEngine.get_user_expired_points(db_session, user_a.id)
    lifetime_points = PointsEngine.get_user_lifetime_points(db_session, user_a.id)

    assert expired_points >= 100
    assert lifetime_points == active_balance + expired_points


def test_idor_points_endpoints(db_session, test_users, test_job_qualifying):
    """User B cannot access User A's points ledger or balance (HTTP 403 Forbidden)."""
    user_a, user_b = test_users
    job = test_job_qualifying

    # Override dependencies for User B
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user_b

    client = TestClient(app)

    try:
        # User B attempts to read User A's balance via user ID endpoint
        resp_user = client.get(f"/api/points/user/{user_a.id}")
        assert resp_user.status_code == 403
        assert "Access forbidden" in resp_user.json()["detail"]

        # User B attempts to read User A's job points ledger
        resp_job = client.get(f"/api/points/job/{job.id}")
        assert resp_job.status_code == 403
        assert "Access forbidden" in resp_job.json()["detail"]

        # User B reads their own balance (should succeed, balance 0)
        resp_self = client.get("/api/points/balance")
        assert resp_self.status_code == 200
        assert resp_self.json()["user_id"] == user_b.id
        assert resp_self.json()["balance"] == 0

    finally:
        app.dependency_overrides.clear()


def test_end_to_end_submit_api_awards_points(db_session, test_users):
    """End-to-end API test: submitting code through the attempts endpoint automatically triggers points award."""
    user_a, _ = test_users

    # Create a qualifying job
    e2e_job = AnalysisJobModel(
        user_id=user_a.id,
        repo_name="org/backend-service",
        github_url="https://github.com/org/backend-service",
        status="completed",
        run_id="run_e2e_points",
        graph_output_json="""{
            "total_files": 10,
            "total_loc": 1200,
            "architecture_overview": {"total_files": 10, "total_loc": 1200},
            "milestones": [
                {
                    "tier": 5,
                    "title": "Auth Handler",
                    "files": ["auth.py"],
                    "test_code": "def test_token(): assert True"
                }
            ]
        }""",
    )
    db_session.add(e2e_job)
    db_session.commit()
    db_session.refresh(e2e_job)

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user_a

    client = TestClient(app)

    try:
        # Submit code for milestone 5 with hint_level_revealed=1
        submit_payload = {
            "submitted_code": "def test_token(): pass\ndef verify(): return True",
            "language": "python",
            "hint_level_revealed": 1,
            "implementation_revealed": False,
        }
        from unittest.mock import patch
        mock_exec = {
            "status": "success",
            "exit_code": 0,
            "stdout": "PASSED [100%]\n1 passed in 0.01s",
            "stderr": "",
            "truncated": False,
        }
        with patch("app.api.attempts.execution_verifier.execute", return_value=mock_exec):
            res = client.post(f"/api/attempts/{e2e_job.id}/5", json=submit_payload)
        assert res.status_code == 200
        data = res.json()
        assert "points_award" in data
        assert data["points_award"] is not None
        assert data["points_award"]["points_awarded"] == 25
        assert data["points_award"]["multiplier_applied"] == 0.50
        assert data["points_award"]["reason"] == "milestone_solved_hint_1"

        # Check balance via points endpoint
        bal_res = client.get("/api/points/balance")
        assert bal_res.status_code == 200
        assert bal_res.json()["balance"] >= 25

        # Check ledger via points endpoint
        led_res = client.get("/api/points/ledger")
        assert led_res.status_code == 200
        assert any(e["milestone_tier"] == 5 for e in led_res.json()["ledger"])

    finally:
        app.dependency_overrides.clear()

