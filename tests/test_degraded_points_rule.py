"""Tests for degraded mode points rule (Step 2 & Step 3).

Proves that:
a) A degraded structural pass awards 0 points.
b) A normal (non-degraded) pass awards the usual points.
c) The points ledger has no new row for the degraded pass.
"""

import json
from unittest.mock import MagicMock, PropertyMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, MilestoneAttemptModel, PointsLedgerModel, UserModel
from app.security.auth import create_access_token
from app.services.piston_health import PistonHealthMonitor
from app.services.points_engine import PointsEngine


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
            github_id=98765,
            github_username="degraded_rule_user",
            email="rule@example.com",
            avatar_url="https://example.com/avatar.png",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        job = AnalysisJobModel(
            user_id=user.id,
            repo_name="psf/requests",
            github_url="https://github.com/psf/requests",
            status="completed",
            run_id="run_degraded_test_01",
            graph_output_json=json.dumps({
                "repo_name": "psf/requests",
                "total_files": 12,
                "total_loc": 2500,
                "architecture_overview": {
                    "total_files": 12,
                    "total_loc": 2500,
                    "total_domains": 4,
                    "primary_language": "python",
                },
                "milestones": [
                    {"tier": 3, "title": "Adapters", "files": ["requests/adapters.py"], "expected_symbols": ["solve"]},
                ],
                "nodes": [
                    {"id": "requests/adapters.py", "type": "function", "tier": 3, "name": "solve", "exports": ["solve"]},
                ],
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
        return {"user": user, "job": job, "token": token, "session_factory": TestingSessionLocal}


# -----------------------------------------------------------------------------
# Unit Tests on PointsEngine
# -----------------------------------------------------------------------------

def test_unit_degraded_pass_awards_zero_points_and_no_ledger_row(auth_user):
    """Proves (a) and (c): PointsEngine awards 0 points and creates NO ledger row when degraded."""
    TestingSessionLocal = auth_user["session_factory"]
    user = auth_user["user"]
    job = auth_user["job"]

    with TestingSessionLocal() as session:
        # Initial state: 0 ledger entries
        assert session.query(PointsLedgerModel).filter_by(user_id=user.id).count() == 0

        attempt = MilestoneAttemptModel(
            user_id=user.id,
            job_id=job.id,
            milestone_tier=3,
            submitted_code="def solve():\n    return 42\n",
            status="structurally_verified",
            grading_method="structural_only",
            grading_details_json=json.dumps({"degraded_mode": True, "passed": True}),
        )
        session.add(attempt)
        session.commit()
        session.refresh(attempt)

        # Call award_points_for_milestone with degraded_mode=True
        award_res = PointsEngine.award_points_for_milestone(
            session=session,
            user_id=user.id,
            job=job,
            milestone_tier=3,
            attempt=attempt,
            degraded_mode=True,
        )

        # (a) Awards 0 points
        assert award_res.points_awarded == 0
        assert award_res.multiplier_applied == 0.0
        assert award_res.reason == "degraded_mode"

        # (c) Points ledger has NO new row
        assert award_res.ledger_entry is None
        ledger_count = session.query(PointsLedgerModel).filter_by(user_id=user.id).count()
        assert ledger_count == 0

        # Balance remains 0
        balance = PointsEngine.get_user_points_balance(session, user.id)
        assert balance == 0


def test_unit_normal_pass_awards_usual_points_and_creates_ledger_row(auth_user):
    """Proves (b): PointsEngine awards usual points and creates a ledger row when normal (non-degraded)."""
    TestingSessionLocal = auth_user["session_factory"]
    user = auth_user["user"]
    job = auth_user["job"]

    with TestingSessionLocal() as session:
        assert session.query(PointsLedgerModel).filter_by(user_id=user.id).count() == 0

        attempt = MilestoneAttemptModel(
            user_id=user.id,
            job_id=job.id,
            milestone_tier=3,
            submitted_code="def solve():\n    return 42\n",
            status="structurally_verified",
            grading_method="structural_only",
            grading_details_json=json.dumps({"degraded_mode": False, "passed": True}),
        )
        session.add(attempt)
        session.commit()
        session.refresh(attempt)

        award_res = PointsEngine.award_points_for_milestone(
            session=session,
            user_id=user.id,
            job=job,
            milestone_tier=3,
            attempt=attempt,
            degraded_mode=False,
        )

        # (b) Awards usual points (50 base)
        assert award_res.points_awarded == 50
        assert award_res.multiplier_applied == 1.0
        assert award_res.reason == "milestone_solved_no_hints"

        # Normal pass creates a new ledger row
        assert award_res.ledger_entry is not None
        assert award_res.ledger_entry.points_awarded == 50
        ledger_count = session.query(PointsLedgerModel).filter_by(user_id=user.id).count()
        assert ledger_count == 1

        # Balance is 50
        balance = PointsEngine.get_user_points_balance(session, user.id)
        assert balance == 50


# -----------------------------------------------------------------------------
# End-to-End API Route Tests: POST /api/attempts/{job_id}/{milestone_tier}
# -----------------------------------------------------------------------------

def test_api_degraded_structural_pass_awards_zero_points_no_ledger_row(client, auth_user):
    """
    End-to-end integration test:
    When Piston execution is unavailable, a Tier 3 structural pass:
    - Sets attempt status='structurally_verified' (unchanged)
    - Returns degraded_mode=True in grading_details (unchanged feedback)
    - Awards 0 points (a)
    - Appends NO new row to points ledger (c)
    """
    job_id = auth_user["job"].id
    user_id = auth_user["user"].id
    headers = {"Authorization": f"Bearer {auth_user['token']}"}
    TestingSessionLocal = auth_user["session_factory"]

    with patch.object(PistonHealthMonitor, "is_healthy", new_callable=PropertyMock, return_value=False), \
         patch("app.api.attempts.grading_engine.exec_verifier.allow_local_fallback", False):

        resp = client.post(
            f"/api/attempts/{job_id}/3",
            headers=headers,
            json={"submitted_code": "def solve():\n    return 42\n", "language": "python"},
        )

        assert resp.status_code == 200
        data = resp.json()

        # Attempt status stays exactly as it is today
        assert data["attempt"]["status"] == "structurally_verified"

        # Feedback returned to user stays exactly as it is today
        assert data["grading_method"] == "structural_only"
        assert data["grading_details"]["degraded_mode"] is True
        assert data["grading_details"]["passed"] is True
        assert "AST structure check passed" in data["grading_details"]["summary"]

        # Rule check: Points award is 0
        assert data["points_award"] is not None
        assert data["points_award"]["points_awarded"] == 0
        assert data["points_award"]["reason"] == "degraded_mode"
        assert data["points_award"]["ledger_id"] is None

        # Verify Points Ledger has NO new row
        with TestingSessionLocal() as session:
            count = session.query(PointsLedgerModel).filter_by(user_id=user_id).count()
            assert count == 0
            balance = PointsEngine.get_user_points_balance(session, user_id)
            assert balance == 0


def test_api_normal_structural_pass_awards_usual_points_and_ledger_row(client, auth_user):
    """
    End-to-end integration test:
    When Piston execution is available, a Tier 3 structural pass:
    - Sets attempt status='structurally_verified'
    - Returns degraded_mode=False
    - Awards usual points (50) (b)
    - Appends a new row to points ledger
    """
    job_id = auth_user["job"].id
    user_id = auth_user["user"].id
    headers = {"Authorization": f"Bearer {auth_user['token']}"}
    TestingSessionLocal = auth_user["session_factory"]

    mock_exec_res = {
        "language": "python",
        "version": "3.10",
        "stdout": "42\n",
        "stderr": "",
        "exit_code": 0,
        "execution_time_ms": 12.0,
        "timed_out": False,
        "status": "success",
    }

    with patch.object(PistonHealthMonitor, "is_healthy", new_callable=PropertyMock, return_value=True), \
         patch("app.api.attempts.grading_engine.exec_verifier.execute", return_value=mock_exec_res):

        resp = client.post(
            f"/api/attempts/{job_id}/3",
            headers=headers,
            json={"submitted_code": "def solve():\n    return 42\n", "language": "python"},
        )

        assert resp.status_code == 200
        data = resp.json()

        # Attempt status
        assert data["attempt"]["status"] == "structurally_verified"

        # Grading details
        assert data["grading_details"]["degraded_mode"] is False
        assert data["grading_details"]["passed"] is True

        # Rule check: Usual points awarded (50)
        assert data["points_award"] is not None
        assert data["points_award"]["points_awarded"] == 50
        assert data["points_award"]["reason"] == "milestone_solved_no_hints"
        assert data["points_award"]["ledger_id"] is not None

        # Verify Points Ledger has 1 new row
        with TestingSessionLocal() as session:
            count = session.query(PointsLedgerModel).filter_by(user_id=user_id).count()
            assert count == 1
            balance = PointsEngine.get_user_points_balance(session, user_id)
            assert balance == 50
