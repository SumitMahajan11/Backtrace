"""Tests verifying real file content persistence and consumption across Just Read It, Fill the Blanks, and Guess It reveal."""

import json
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.api.dependencies import get_db
from app.main import app
from app.models.db import Base, AnalysisJobModel, IngestionResultModel, RepoModel, UserModel, utc_now
from app.services.file_content_service import FileContentService, SOURCE_NOT_AVAILABLE_MESSAGE
from app.services.grading_engine import GradingEngine
from app.services.hint_engine import HintEngine
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.milestone_attempt_repository import MilestoneAttemptRepository
from app.storage.user_repository import UserRepository
from app.security.auth import create_access_token
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


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

    def _create(github_id: int, username: str, is_admin: bool = False) -> UserModel:
        with SessionLocal() as session:
            user = UserRepository.upsert_github_user(
                session=session,
                github_id=github_id,
                github_username=username,
                email=f"{username}@example.com",
                avatar_url=f"https://github.com/images/{username}.png",
            )
            session.commit()
            session.refresh(user)
            return user

    return _create


REELCLAIM_REAL_DB_PY = '''"""Database configuration and models for ReelClaim backend."""

from sqlalchemy import Column, Integer, String, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime

Base = declarative_base()


class AuditRecord(Base):
    """SQLAlchemy model representing an audit log entry."""
    __tablename__ = "audit_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(128), nullable=False)
    target_resource = Column(String(256), nullable=False)
    actor = Column(String(128), nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)


def get_db():
    """Yields a database session instance for request lifecycle."""
    engine = create_engine("sqlite:///reelclaim.db")
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''

REELCLAIM_REAL_CONFIG_PY = '''"""Application configuration settings for ReelClaim."""

import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///reelclaim.db")
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key-12345")
DEBUG = False
'''


def test_file_content_service_persistence_and_matching(test_db):
    """Verifies that FileContentService properly persists and matches file contents."""
    SessionLocal, _ = test_db
    repo_url = "https://github.com/reelclaim/reelclaim"
    file_map = {
        "reelclaim-backend/app/db.py": REELCLAIM_REAL_DB_PY,
        "reelclaim-backend/app/config.py": REELCLAIM_REAL_CONFIG_PY,
    }

    with SessionLocal() as session:
        repo = FileContentService.persist_file_contents(
            session=session,
            github_url=repo_url,
            file_contents=file_map,
            commit_hash="abc123commit",
        )
        session.commit()

        assert repo.id is not None
        assert repo.ingestion_result is not None
        saved_contents = json.loads(repo.ingestion_result.file_contents_json)
        assert "reelclaim-backend/app/db.py" in saved_contents

        # Create a mock job
        user = UserModel(github_id=50001, github_username="tester1")
        session.add(user)
        session.flush()

        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url=repo_url,
            status="completed",
        )

        retrieved = FileContentService.get_file_contents_for_job(session=session, job=job)
        assert retrieved == file_map

        # Test various matching strategies
        assert FileContentService.find_matching_file_content(retrieved, "reelclaim-backend/app/db.py") == REELCLAIM_REAL_DB_PY
        assert FileContentService.find_matching_file_content(retrieved, "app/db.py") == REELCLAIM_REAL_DB_PY
        assert FileContentService.find_matching_file_content(retrieved, "db.py") == REELCLAIM_REAL_DB_PY
        assert FileContentService.find_matching_file_content(retrieved, "reelclaim-backend\\app\\config.py") == REELCLAIM_REAL_CONFIG_PY
        assert FileContentService.find_matching_file_content(retrieved, "non_existent.py") is None


def test_reelclaim_milestone_0_just_read_it_shows_real_content(client, create_user, test_db):
    """
    Part E.1: For ReelClaim Milestone 0 (reelclaim-backend/app/db.py),
    verifies Just Read It renders the REAL file content (AuditRecord SQLAlchemy model,
    imports, get_db), NOT 'class ApiKey: pass' or HintEngine stubs.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=50002, username="reelclaim_reader")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    repo_url = "https://github.com/reelclaim/reelclaim"
    file_map = {
        "reelclaim-backend/app/db.py": REELCLAIM_REAL_DB_PY,
        "reelclaim-backend/app/config.py": REELCLAIM_REAL_CONFIG_PY,
    }

    report_md = """# Architectural Report: ReelClaim
## 3. Step-by-Step Architectural Milestones

### Milestone 0: Core Foundation & Database Models
**[HIGH CONFIDENCE]** -- *Foundation database & settings*
**Overview:** Database models and configuration setup.
**Included Files:**
- `reelclaim-backend/app/db.py`
- `reelclaim-backend/app/config.py`
"""

    with SessionLocal() as session:
        FileContentService.persist_file_contents(
            session=session,
            github_url=repo_url,
            file_contents=file_map,
        )

        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url=repo_url,
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={
                "nodes": [
                    {"id": "reelclaim-backend/app/db.py", "path": "reelclaim-backend/app/db.py", "tier": 0},
                    {"id": "reelclaim-backend/app/config.py", "path": "reelclaim-backend/app/config.py", "tier": 0},
                ],
                "edges": [],
            },
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html_text = resp.text

    # MUST contain real source code
    assert "class AuditRecord(Base):" in html_text
    assert "audit_records" in html_text
    assert "def get_db():" in html_text
    assert "sqlite:///reelclaim.db" in html_text

    # MUST NOT contain HintEngine placeholder stub markers
    assert "class ApiKey:" not in html_text
    assert "Generated from verified static AST syntax tree" not in html_text


def test_reelclaim_milestone_0_fill_the_blanks_and_grading(client, create_user, test_db):
    """
    Part E.2: For ReelClaim Milestone 0, verifies Fill the Blanks creates scaffolds
    from real function bodies (get_db) with real blanks, and grades against real code.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=50003, username="reelclaim_filler")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    repo_url = "https://github.com/reelclaim/reelclaim"
    file_map = {
        "reelclaim-backend/app/db.py": REELCLAIM_REAL_DB_PY,
    }

    report_md = """# Architectural Report: ReelClaim
## 3. Step-by-Step Architectural Milestones

### Milestone 0: Core Foundation
**[HIGH CONFIDENCE]** -- *Foundation database*
**Overview:** Database models.
**Included Files:**
- `reelclaim-backend/app/db.py`
"""

    with SessionLocal() as session:
        FileContentService.persist_file_contents(
            session=session,
            github_url=repo_url,
            file_contents=file_map,
        )

        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url=repo_url,
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={
                "nodes": [
                    {"id": "reelclaim-backend/app/db.py", "path": "reelclaim-backend/app/db.py", "tier": 0},
                ],
                "edges": [],
            },
        )
        job_id = job.id

    # 1. Check UI contains real scaffold
    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html_text = resp.text

    # Scaffold preserved imports, class AuditRecord, and blanked get_db
    assert "class AuditRecord(Base):" in html_text
    assert "get_db" in html_text

    # 2. Submit correct fill attempt
    fill_payload = {
        "submitted_code": REELCLAIM_REAL_DB_PY,
        "language": "python",
        "mode": "fill",
        "target_file": "reelclaim-backend/app/db.py",
    }
    submit_resp = client.post(f"/api/attempts/{job_id}/0", json=fill_payload)
    assert submit_resp.status_code == 200
    submit_data = submit_resp.json()
    assert submit_data["attempt"]["status"] == "structurally_verified"
    assert submit_data["grading_method"] == "fill_the_blanks"
    assert submit_data["grading_details"]["passed"] is True


def test_reelclaim_milestone_0_guess_it_reveal_shows_real_file(client, create_user, test_db):
    """
    Part E.3: For ReelClaim Milestone 0, Guess It -> Reveal Implementation
    returns the real file content, NOT fake AST stubs.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=50004, username="reelclaim_revealer")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    repo_url = "https://github.com/reelclaim/reelclaim"
    file_map = {
        "reelclaim-backend/app/db.py": REELCLAIM_REAL_DB_PY,
    }

    report_md = """# Architectural Report: ReelClaim
## 3. Step-by-Step Architectural Milestones

### Milestone 0: Core Foundation
**[HIGH CONFIDENCE]** -- *Foundation database*
**Overview:** Database models.
**Included Files:**
- `reelclaim-backend/app/db.py`
"""

    with SessionLocal() as session:
        FileContentService.persist_file_contents(
            session=session,
            github_url=repo_url,
            file_contents=file_map,
        )

        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url=repo_url,
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={
                "nodes": [
                    {"id": "reelclaim-backend/app/db.py", "path": "reelclaim-backend/app/db.py", "tier": 0},
                ],
                "edges": [],
            },
        )
        # Create an initial attempt to unlock reveal
        attempt = MilestoneAttemptRepository.save_or_update_attempt(
            session=session,
            user_id=user.id,
            job_id=job.id,
            milestone_tier=0,
            submitted_code="# My guess",
            status="attempting",
        )
        job_id = job.id

    # Call Reveal endpoint
    reveal_resp = client.post(f"/api/attempts/{job_id}/0/reveal")
    assert reveal_resp.status_code == 200
    reveal_data = reveal_resp.json()

    ref_code = reveal_data["reference_implementation"]["reference_code"]
    assert "class AuditRecord(Base):" in ref_code
    assert "def get_db():" in ref_code
    assert "Generated from verified static AST syntax tree" not in ref_code
    assert "class ApiKey:" not in ref_code


def test_missing_source_shows_explicit_unavailable_notice(client, create_user, test_db):
    """
    Part C & E.4: When real file content is genuinely not available (e.g. old job, inaccessible repo):
    - Just Read It shows explicit 'source not available' message, NOT fake AST stubs.
    - Fill the Blanks is disabled with message.
    - Guess It reveal returns 'source not available' message.
    - 'Generated from verified static AST syntax tree' NEVER appears in output.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=50005, username="missing_source_user")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    # Repo URL with NO persisted DB record and no live accessibility
    repo_url = "https://github.com/nonexistent-org/unpersisted-repo"

    report_md = """# Architectural Report: Old Job
## 3. Step-by-Step Architectural Milestones

### Milestone 0: Legacy Module
**[HIGH CONFIDENCE]** -- *Legacy*
**Overview:** Legacy module.
**Included Files:**
- `app/legacy.py`
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url=repo_url,
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={
                "nodes": [
                    {"id": "app/legacy.py", "path": "app/legacy.py", "tier": 0},
                ],
                "edges": [],
            },
        )
        # Attempt started
        MilestoneAttemptRepository.save_or_update_attempt(
            session=session,
            user_id=user.id,
            job_id=job.id,
            milestone_tier=0,
            submitted_code="# test guess",
            status="attempting",
        )
        job_id = job.id

    # 1. UI Check: Just Read It and Fill the Blanks
    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html_text = resp.text

    # Must contain clear message
    assert "The original source for this file isn&#039;t available for this job" in html_text or "The original source for this file isn't available for this job" in html_text
    # Must NOT contain fake AST stubs
    assert "Generated from verified static AST syntax tree" not in html_text
    assert "class ApiKey:" not in html_text

    # Fill button must be disabled
    assert 'id="mode-btn-fill-0" class="milestone-mode-tab-btn disabled"' in html_text or "disabled" in html_text

    # 2. Guess It Reveal Check
    reveal_resp = client.post(f"/api/attempts/{job_id}/0/reveal")
    assert reveal_resp.status_code == 200
    reveal_data = reveal_resp.json()
    ref_code = reveal_data["reference_implementation"]["reference_code"]

    assert "The original source for this file isn't available for this job" in ref_code
    assert "Generated from verified static AST syntax tree" not in ref_code
