"""Tests for Milestone Attempt Data Model, Repository, IDOR Defense, and XSS Protection (Prompt 11)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import MilestoneAttemptModel, UserModel
from app.security.auth import create_access_token
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.milestone_attempt_repository import MilestoneAttemptRepository
from app.storage.user_repository import UserRepository
from app.utils.file_filter import MAX_FILE_SIZE_BYTES


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
            )
            session.commit()
            session.refresh(user)
            return user

    return _create


def test_milestone_attempt_unique_constraint(test_db, create_user):
    """DB-level constraint: One row per (user, job, milestone)."""
    SessionLocal, _ = test_db
    user = create_user(github_id=1001, username="test_dev")

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/example/repo",
            status="completed",
        )
        job_id = job.id

    # Insert first attempt
    with SessionLocal() as session:
        attempt1 = MilestoneAttemptModel(
            user_id=user.id,
            job_id=job_id,
            milestone_tier=0,
            submitted_code="def func_a(): pass",
            status="attempting",
        )
        session.add(attempt1)
        session.commit()

    # Attempt to insert second attempt for same (user, job, milestone_tier) must raise IntegrityError
    with SessionLocal() as session:
        attempt2 = MilestoneAttemptModel(
            user_id=user.id,
            job_id=job_id,
            milestone_tier=0,
            submitted_code="def func_b(): pass",
            status="attempting",
        )
        session.add(attempt2)
        with pytest.raises(IntegrityError):
            session.commit()


def test_milestone_attempt_repository_upsert(test_db, create_user):
    """Repository save_or_update_attempt safely updates existing records."""
    SessionLocal, _ = test_db
    user = create_user(github_id=1002, username="test_upsert")

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/example/repo2",
            status="completed",
        )
        job_id = job.id

    with SessionLocal() as session:
        # First save
        att1 = MilestoneAttemptRepository.save_or_update_attempt(
            session=session,
            user_id=user.id,
            job_id=job_id,
            milestone_tier=1,
            submitted_code="def v1(): pass",
            status="attempting",
        )
        att1_id = att1.id
        assert att1.status == "attempting"

        # Second save (update)
        att2 = MilestoneAttemptRepository.save_or_update_attempt(
            session=session,
            user_id=user.id,
            job_id=job_id,
            milestone_tier=1,
            submitted_code="def v2(): pass",
            status="structurally_verified",
            hint_level_revealed=1,
        )
        assert att2.id == att1_id
        assert att2.status == "structurally_verified"
        assert att2.submitted_code == "def v2(): pass"
        assert att2.hint_level_revealed == 1


def test_milestone_attempt_idor_defense(client, create_user, test_db):
    """Threat Model: User B cannot GET, POST, or inspect User A's milestone attempt records."""
    SessionLocal, _ = test_db

    # User A (Owner)
    user_a = create_user(github_id=2001, username="user_a_owner")
    token_a = create_access_token(user_id=user_a.id, github_id=user_a.github_id, github_username=user_a.github_username)

    # User B (Attacker)
    user_b = create_user(github_id=2002, username="user_b_attacker")
    token_b = create_access_token(user_id=user_b.id, github_id=user_b.github_id, github_username=user_b.github_username)

    with SessionLocal() as session:
        job_a = AnalysisJobRepository.create_job(
            session=session,
            user_id=user_a.id,
            repo_url="https://github.com/secret/repo-a",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job_a.id,
            status="completed",
            graph_data={
                "nodes": [
                    {"id": "core.py", "tier": 0, "exports": ["SecretClass", "solve_equation"]}
                ]
            },
        )
        job_a_id = job_a.id

        # User A saves an attempt
        attempt_a = MilestoneAttemptRepository.save_or_update_attempt(
            session=session,
            user_id=user_a.id,
            job_id=job_a_id,
            milestone_tier=0,
            submitted_code="class SecretClass: pass\ndef solve_equation(): pass",
            status="structurally_verified",
        )
        attempt_a_id = attempt_a.id

    # 1. User B tries to GET User A's milestone attempt -> MUST BE 403 FORBIDDEN
    client.cookies.set("access_token", token_b)
    resp_get_tier = client.get(f"/api/attempts/{job_a_id}/0")
    assert resp_get_tier.status_code == 403
    assert "Access forbidden: You do not own this analysis job" in resp_get_tier.json()["detail"]

    # 2. User B tries to GET User A's attempt via direct attempt ID -> MUST BE 403 FORBIDDEN
    resp_get_by_id = client.get(f"/api/attempts/by-id/{attempt_a_id}")
    assert resp_get_by_id.status_code == 403
    assert "Access forbidden: You do not own this milestone attempt" in resp_get_by_id.json()["detail"]

    # 3. User B tries to POST/submit to User A's job -> MUST BE 403 FORBIDDEN
    resp_post = client.post(
        f"/api/attempts/{job_a_id}/0",
        json={"submitted_code": "def malicious(): pass"},
    )
    assert resp_post.status_code == 403
    assert "Access forbidden: You do not own this analysis job" in resp_post.json()["detail"]

    # 4. User B tries to view rendered code for User A's job -> MUST BE 403 FORBIDDEN
    resp_view = client.get(f"/api/attempts/{job_a_id}/0/view")
    assert resp_view.status_code == 403
    assert "Access forbidden: You do not own this analysis job" in resp_view.json()["detail"]

    # 5. User A can successfully access all endpoints -> 200 OK
    client.cookies.set("access_token", token_a)
    resp_owner_get = client.get(f"/api/attempts/{job_a_id}/0")
    assert resp_owner_get.status_code == 200
    assert resp_owner_get.json()["attempt"]["status"] == "structurally_verified"

    resp_owner_by_id = client.get(f"/api/attempts/by-id/{attempt_a_id}")
    assert resp_owner_by_id.status_code == 200
    assert resp_owner_by_id.json()["submitted_code"] == "class SecretClass: pass\ndef solve_equation(): pass"


def test_milestone_attempt_stored_xss_protection(client, create_user, test_db):
    """Threat Model: Code containing XSS payload is stored as text and escaped in HTML view."""
    SessionLocal, _ = test_db
    user = create_user(github_id=3001, username="xss_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/example/xss-target",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            graph_data={"nodes": [{"id": "main.py", "tier": 0, "exports": ["safe_func"]}]},
        )
        job_id = job.id

    client.cookies.set("access_token", token)

    xss_payload = """
# Exploit demonstration
<script>alert('XSS_EXECUTION')</script>
<img src=x onerror=alert(1)>
def safe_func():
    pass
"""
    resp_submit = client.post(
        f"/api/attempts/{job_id}/0",
        json={"submitted_code": xss_payload, "language": "python"},
    )
    assert resp_submit.status_code == 200

    # View rendered page
    resp_view = client.get(f"/api/attempts/{job_id}/0/view")
    assert resp_view.status_code == 200
    html_text = resp_view.text

    # MUST NOT contain unescaped raw <script> tag
    assert "<script>alert('XSS_EXECUTION')</script>" not in html_text
    # MUST contain escaped HTML entities
    assert "&lt;script&gt;alert(&#x27;XSS_EXECUTION&#x27;)&lt;/script&gt;" in html_text or "&lt;script&gt;" in html_text
    assert "&lt;img src=x onerror=alert(1)&gt;" in html_text or "&lt;img" in html_text


def test_milestone_attempt_dos_oversized_payload(client, create_user, test_db):
    """Threat Model: Code submission exceeding 1MB is rejected with 413 Payload Too Large."""
    SessionLocal, _ = test_db
    user = create_user(github_id=4001, username="dos_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/example/dos-target",
            status="completed",
        )
        job_id = job.id

    client.cookies.set("access_token", token)

    oversized_code = "# " + ("B" * (MAX_FILE_SIZE_BYTES + 2048))
    resp = client.post(
        f"/api/attempts/{job_id}/0",
        json={"submitted_code": oversized_code, "language": "python"},
    )
    assert resp.status_code == 413
    assert "exceeds maximum limit" in resp.json()["detail"]


def test_mark_milestone_reviewed_api_endpoint(client, create_user, test_db):
    """Marks milestone as reviewed (Just Read It mode) and verifies status and grading_method."""
    SessionLocal, _ = test_db
    user = create_user(github_id=5001, username="reviewer_dev")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/example/review-target",
            status="completed",
        )
        job_id = job.id

    client.cookies.set("access_token", token)

    resp = client.post(f"/api/attempts/{job_id}/0/review")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "structurally_verified"
    assert data["grading_method"] == "reviewed"
    assert data["attempt"]["status"] == "structurally_verified"


def test_fill_the_blanks_submission_and_immediate_hints(client, create_user, test_db):
    """Verifies that Fill the Blanks submission evaluates scoped blanks and allows immediate hint access."""
    SessionLocal, _ = test_db
    user = create_user(github_id=6001, username="fill_dev")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)

    sample_source = """def add_numbers(a, b):
    return a + b
"""
    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/example/fill-target",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            graph_data={
                "nodes": [{"id": "calc.py", "path": "calc.py", "tier": 0, "source_code": sample_source}],
                "milestones": [{"tier": 0, "included_files": ["calc.py"]}],
            },
        )
        job_id = job.id

    client.cookies.set("access_token", token)

    # 1. Untouched milestone hint in Guess mode is locked (400 Bad Request)
    resp_guess_hint = client.post(f"/api/attempts/{job_id}/0/hint")
    assert resp_guess_hint.status_code == 400
    assert "locked until you make your first implementation attempt" in resp_guess_hint.json()["detail"]

    # 2. Untouched milestone hint in Fill mode is immediately accessible
    resp_fill_hint = client.post(f"/api/attempts/{job_id}/0/hint?mode=fill")
    assert resp_fill_hint.status_code == 200
    data_hint = resp_fill_hint.json()
    assert data_hint["hint_level_revealed"] == 1
    assert data_hint["hint_1"] is not None

    # 3. Submit Fill the Blanks submission
    resp_submit = client.post(
        f"/api/attempts/{job_id}/0",
        json={
            "submitted_code": "def add_numbers(a, b):\n    return a + b\n",
            "mode": "fill",
            "target_file": "calc.py",
        },
    )
    assert resp_submit.status_code == 200
    data_submit = resp_submit.json()
    assert data_submit["grading_method"] == "fill_the_blanks"
    assert data_submit["verification"]["structurally_verified"] is True


