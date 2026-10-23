"""Tests for 30-day retention cleanup policy and report handling when repo files have expired."""

import json
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.main import app
from app.models.db import (
    AnalysisJobModel,
    Base,
    IngestionResultModel,
    RepoModel,
    UserModel,
    utc_now,
)
from app.security.auth import create_access_token
from app.services.file_content_service import FileContentService
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.repository import StorageRepository


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


def test_expired_non_showcase_repo_is_deleted(test_db):
    """(a) An expired non-showcase repo is deleted by retention cleanup."""
    SessionLocal, _ = test_db
    past_date = utc_now() - timedelta(days=35)

    with SessionLocal() as session:
        repo = RepoModel(
            github_url="https://github.com/regular/expired-repo",
            commit_hash="hash_expired_regular",
            status="complete",
            created_at=past_date - timedelta(days=1),
            expires_at=past_date,
            keep_longer=False,
        )
        session.add(repo)
        session.commit()

        deleted = StorageRepository.cleanup_expired_records(session)
        session.commit()

        assert deleted == 1
        rem = session.query(RepoModel).filter(RepoModel.github_url == "https://github.com/regular/expired-repo").first()
        assert rem is None


def test_expired_repo_with_keep_longer_is_not_deleted(test_db):
    """(b) An expired repo with keep_longer=True is NOT deleted by retention cleanup."""
    SessionLocal, _ = test_db
    past_date = utc_now() - timedelta(days=35)

    with SessionLocal() as session:
        repo = RepoModel(
            github_url="https://github.com/optin/keep-repo",
            commit_hash="hash_optin_keep",
            status="complete",
            created_at=past_date - timedelta(days=1),
            expires_at=past_date,
            keep_longer=True,
        )
        session.add(repo)
        session.commit()

        deleted = StorageRepository.cleanup_expired_records(session)
        session.commit()

        assert deleted == 0
        rem = session.query(RepoModel).filter(RepoModel.github_url == "https://github.com/optin/keep-repo").first()
        assert rem is not None
        assert rem.keep_longer is True


def test_report_returns_200_and_shows_expired_message_when_repo_rows_deleted(test_db, client):
    """(c) GET /report/<job_id> returns 200 without a crash for a job whose repo rows were deleted,
    and the source file viewer shows a 'source files expired' message instead of an error."""
    SessionLocal, _ = test_db
    past_date = utc_now() - timedelta(days=40)
    repo_url = "https://github.com/test-org/deleted-files-repo"

    with SessionLocal() as session:
        user = UserModel(
            github_id=98765,
            github_username="retention_tester",
            email="retention_tester@example.com",
            avatar_url="https://github.com/retention_tester.png",
        )
        session.add(user)
        session.flush()

        # Create repo and its ingestion result initially
        repo = RepoModel(
            github_url=repo_url,
            commit_hash="commit_hash_123",
            status="complete",
            created_at=past_date - timedelta(days=1),
            expires_at=past_date,
            keep_longer=False,
        )
        session.add(repo)
        session.flush()

        ing = IngestionResultModel(
            repo_id=repo.id,
            file_tree_json=json.dumps([{"path": "app/core.py"}]),
            file_contents_json=json.dumps({"app/core.py": "def secret_algo(): pass"}),
            skipped_files_json="[]",
            redaction_count=0,
            clone_duration_ms=50,
        )
        session.add(ing)
        session.flush()

        # Create completed analysis job
        report_md = """# Architecture Dossier: Deleted Files Repo
## 3. Step-by-Step Architectural Milestones

### Milestone 0: Core Architecture
**[HIGH CONFIDENCE]** -- *Core logic*
**Overview:** Core logic module.
**Included Files:**
- `app/core.py`
"""
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
                    {"id": "app/core.py", "path": "app/core.py", "tier": 0},
                ],
                "edges": [],
            },
        )
        job_id = job.id
        user_id = user.id
        user_gh_id = user.github_id
        user_gh_login = user.github_username

        # Now execute retention cleanup to delete the repo and ingestion rows
        deleted = StorageRepository.cleanup_expired_records(session)
        session.commit()
        assert deleted == 1

        # Verify repo row is deleted
        remaining_repo = session.query(RepoModel).filter(RepoModel.github_url == repo_url).first()
        assert remaining_repo is None

    # Authenticate client as the job owner
    token = create_access_token(user_id=user_id, github_id=user_gh_id, github_username=user_gh_login)
    client.cookies.set("access_token", token)

    # Request the report page
    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
    html = resp.text

    # Verify that the source file viewer shows "source files expired" message instead of crashing or showing an error
    assert "source files expired" in html.lower()
