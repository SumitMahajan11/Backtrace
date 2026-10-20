"""Tests for sandbox off points rule (SANDBOX_ENABLED=false).

STEP 1 & STEP 3 verification:
(a) fill-mode pass with SANDBOX_ENABLED=false gives 0 points and no ledger row.
(b) guess-mode structural pass with SANDBOX_ENABLED=false gives 0 points and no ledger row.
(c) with SANDBOX_ENABLED=true both still give the usual points and create a ledger row.
STEP 2 UI text:
Under the Submit button in fill mode, show: "No points are awarded on this demo."
only when sandbox_enabled is false. Nothing changes when it is true.
"""

import json
from unittest.mock import patch
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
    sample_source = "def solve():\n    return 42\n"

    with TestingSessionLocal() as session:
        user = UserModel(
            github_id=881122,
            github_username="sandbox_rule_tester",
            email="tester@example.com",
            avatar_url="https://example.com/avatar.png",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        job = AnalysisJobModel(
            user_id=user.id,
            repo_name="org/sandbox-test-repo",
            github_url="https://github.com/org/sandbox-test-repo",
            status="completed",
            run_id="run_sandbox_off_test_01",
            report_markdown="""# Architectural Report
## 3. Step-by-Step Architectural Milestones

### Milestone 0: Core Module
**[HIGH CONFIDENCE]** -- *Core module*
**Overview:** Core implementation
**Included Files:**
- `core.py`
""",
            graph_output_json=json.dumps({
                "repo_name": "org/sandbox-test-repo",
                "total_files": 10,
                "total_loc": 1500,
                "architecture_overview": {
                    "total_files": 10,
                    "total_loc": 1500,
                    "total_domains": 3,
                    "primary_language": "python",
                },
                "milestones": [
                    {
                        "tier": 0,
                        "title": "Core Module",
                        "files": ["core.py"],
                        "expected_symbols": ["solve"],
                        "grading_tier": "structural_only",
                    },
                ],
                "nodes": [
                    {
                        "id": "core.py",
                        "path": "core.py",
                        "tier": 0,
                        "name": "solve",
                        "type": "function",
                        "exports": ["solve"],
                        "source_code": sample_source,
                    },
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

    return {
        "user": user,
        "job": job,
        "token": token,
        "session_factory": TestingSessionLocal,
    }


# =============================================================================
# Unit Tests for PointsEngine.award_points_for_milestone
# =============================================================================

def test_unit_points_engine_sandbox_disabled_fill_mode(auth_user, monkeypatch):
    """(a) Unit test: Fill-mode pass with SANDBOX_ENABLED=false awards 0 points and no ledger row."""
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    TestingSessionLocal = auth_user["session_factory"]
    user = auth_user["user"]
    job = auth_user["job"]

    with TestingSessionLocal() as session:
        assert session.query(PointsLedgerModel).filter_by(user_id=user.id).count() == 0

        attempt = MilestoneAttemptModel(
            user_id=user.id,
            job_id=job.id,
            milestone_tier=0,
            submitted_code="def solve():\n    return 42\n",
            status="structurally_verified",
            grading_method="fill_the_blanks",
            grading_details_json=json.dumps({"degraded_mode": False, "passed": True}),
        )
        session.add(attempt)
        session.commit()
        session.refresh(attempt)

        award_res = PointsEngine.award_points_for_milestone(
            session=session,
            user_id=user.id,
            job=job,
            milestone_tier=0,
            attempt=attempt,
            degraded_mode=False,
        )

        assert award_res.points_awarded == 0
        assert award_res.multiplier_applied == 0.0
        assert award_res.reason == "sandbox_disabled"
        assert award_res.ledger_entry is None

        # Verify no ledger row created
        assert session.query(PointsLedgerModel).filter_by(user_id=user.id).count() == 0
        assert PointsEngine.get_user_points_balance(session, user.id) == 0


def test_unit_points_engine_sandbox_disabled_guess_structural(auth_user, monkeypatch):
    """(b) Unit test: Guess-mode structural pass with SANDBOX_ENABLED=false awards 0 points and no ledger row."""
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    TestingSessionLocal = auth_user["session_factory"]
    user = auth_user["user"]
    job = auth_user["job"]

    with TestingSessionLocal() as session:
        assert session.query(PointsLedgerModel).filter_by(user_id=user.id).count() == 0

        attempt = MilestoneAttemptModel(
            user_id=user.id,
            job_id=job.id,
            milestone_tier=0,
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
            milestone_tier=0,
            attempt=attempt,
            degraded_mode=False,
        )

        assert award_res.points_awarded == 0
        assert award_res.multiplier_applied == 0.0
        assert award_res.reason == "sandbox_disabled"
        assert award_res.ledger_entry is None

        assert session.query(PointsLedgerModel).filter_by(user_id=user.id).count() == 0
        assert PointsEngine.get_user_points_balance(session, user.id) == 0


def test_unit_points_engine_sandbox_enabled_awards_usual_points(auth_user, monkeypatch):
    """(c) Unit test: With SANDBOX_ENABLED=true both fill and guess pass give usual points and ledger row."""
    monkeypatch.setenv("SANDBOX_ENABLED", "true")
    TestingSessionLocal = auth_user["session_factory"]
    user = auth_user["user"]
    job = auth_user["job"]

    with TestingSessionLocal() as session:
        assert session.query(PointsLedgerModel).filter_by(user_id=user.id).count() == 0

        # Fill-mode attempt
        attempt_fill = MilestoneAttemptModel(
            user_id=user.id,
            job_id=job.id,
            milestone_tier=0,
            submitted_code="def solve():\n    return 42\n",
            status="structurally_verified",
            grading_method="fill_the_blanks",
            grading_details_json=json.dumps({"degraded_mode": False, "passed": True}),
        )
        session.add(attempt_fill)
        session.commit()
        session.refresh(attempt_fill)

        award_fill = PointsEngine.award_points_for_milestone(
            session=session,
            user_id=user.id,
            job=job,
            milestone_tier=0,
            attempt=attempt_fill,
            degraded_mode=False,
        )

        assert award_fill.points_awarded == 50
        assert award_fill.multiplier_applied == 1.0
        assert award_fill.ledger_entry is not None
        assert session.query(PointsLedgerModel).filter_by(user_id=user.id).count() == 1
        assert PointsEngine.get_user_points_balance(session, user.id) == 50


# =============================================================================
# End-to-End API Route Tests: POST /api/attempts/{job_id}/{tier}
# =============================================================================

def test_api_fill_mode_pass_sandbox_disabled_awards_zero_points(client, auth_user, monkeypatch):
    """
    (a) End-to-end API: fill-mode pass with SANDBOX_ENABLED=false
    gives 0 points and no ledger row.
    """
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    job_id = auth_user["job"].id
    user_id = auth_user["user"].id
    headers = {"Authorization": f"Bearer {auth_user['token']}"}
    TestingSessionLocal = auth_user["session_factory"]

    resp = client.post(
        f"/api/attempts/{job_id}/0",
        headers=headers,
        json={
            "submitted_code": "def solve():\n    return 42\n",
            "language": "python",
            "mode": "fill",
            "target_file": "core.py",
        },
    )

    assert resp.status_code == 200
    data = resp.json()

    assert data["attempt"]["status"] == "structurally_verified"
    assert data["grading_method"] == "fill_the_blanks"

    # Points award must be 0
    assert data["points_award"] is not None
    assert data["points_award"]["points_awarded"] == 0
    assert data["points_award"]["reason"] == "sandbox_disabled"
    assert data["points_award"]["ledger_id"] is None

    # Database verification: no row in points ledger
    with TestingSessionLocal() as session:
        count = session.query(PointsLedgerModel).filter_by(user_id=user_id).count()
        assert count == 0
        balance = PointsEngine.get_user_points_balance(session, user_id)
        assert balance == 0


def test_api_guess_mode_structural_pass_sandbox_disabled_awards_zero_points(client, auth_user, monkeypatch):
    """
    (b) End-to-end API: guess-mode structural pass with SANDBOX_ENABLED=false
    gives 0 points and no ledger row.
    """
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    job_id = auth_user["job"].id
    user_id = auth_user["user"].id
    headers = {"Authorization": f"Bearer {auth_user['token']}"}
    TestingSessionLocal = auth_user["session_factory"]

    resp = client.post(
        f"/api/attempts/{job_id}/0",
        headers=headers,
        json={
            "submitted_code": "def solve():\n    return 42\n",
            "language": "python",
            "mode": "guess",
        },
    )

    assert resp.status_code == 200
    data = resp.json()

    assert data["attempt"]["status"] == "structurally_verified"
    assert data["grading_method"] == "structural_only"

    # Points award must be 0
    assert data["points_award"] is not None
    assert data["points_award"]["points_awarded"] == 0
    assert data["points_award"]["reason"] == "sandbox_disabled"
    assert data["points_award"]["ledger_id"] is None

    # Database verification: no row in points ledger
    with TestingSessionLocal() as session:
        count = session.query(PointsLedgerModel).filter_by(user_id=user_id).count()
        assert count == 0
        balance = PointsEngine.get_user_points_balance(session, user_id)
        assert balance == 0


def test_api_sandbox_enabled_awards_usual_points(client, auth_user, monkeypatch):
    """
    (c) End-to-end API: with SANDBOX_ENABLED=true, both fill-mode and guess-mode
    structural passes still give the usual points and ledger row.
    """
    monkeypatch.setenv("SANDBOX_ENABLED", "true")
    job_id = auth_user["job"].id
    user_id = auth_user["user"].id
    headers = {"Authorization": f"Bearer {auth_user['token']}"}
    TestingSessionLocal = auth_user["session_factory"]

    resp = client.post(
        f"/api/attempts/{job_id}/0",
        headers=headers,
        json={
            "submitted_code": "def solve():\n    return 42\n",
            "language": "python",
            "mode": "fill",
            "target_file": "core.py",
        },
    )

    assert resp.status_code == 200
    data = resp.json()

    assert data["attempt"]["status"] == "structurally_verified"
    assert data["points_award"] is not None
    assert data["points_award"]["points_awarded"] == 50
    assert data["points_award"]["ledger_id"] is not None

    with TestingSessionLocal() as session:
        count = session.query(PointsLedgerModel).filter_by(user_id=user_id).count()
        assert count == 1
        balance = PointsEngine.get_user_points_balance(session, user_id)
        assert balance == 50


# =============================================================================
# STEP 2 UI Text Tests
# =============================================================================

def test_ui_fill_mode_submit_note_when_sandbox_disabled(client, auth_user, monkeypatch):
    """
    STEP 2: In fill mode, under the Submit button, show:
    "No points are awarded on this demo." only when sandbox_enabled is false.
    Nothing changes when it is true.
    """
    job_id = auth_user["job"].id
    headers = {"Authorization": f"Bearer {auth_user['token']}"}

    # 1. When SANDBOX_ENABLED=false: show the text under Submit button in fill mode
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    resp_false = client.get(f"/report/{job_id}", headers=headers)
    assert resp_false.status_code == 200
    html_false = resp_false.text
    assert "No points are awarded on this demo." in html_false

    # 2. When SANDBOX_ENABLED=true: do not show the text
    monkeypatch.setenv("SANDBOX_ENABLED", "true")
    resp_true = client.get(f"/report/{job_id}", headers=headers)
    assert resp_true.status_code == 200
    html_true = resp_true.text
    assert "No points are awarded on this demo." not in html_true
