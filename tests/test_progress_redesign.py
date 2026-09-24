"""Tests for Prompt 7: Progress Pipeline Redesign, 11 Distinct Stages, and Telemetry Cleanup."""

import os
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


def test_progress_unauthenticated_redirect(client):
    """Unauthenticated users visiting /progress/{job_id} must be redirected to /login."""
    resp = client.get("/progress/job-123", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_progress_idor_protection(client, create_user, test_db):
    """User B cannot view User A's progress page (returns 403)."""
    user1 = create_user(github_id=666001, username="prog_user1")
    user2 = create_user(github_id=666002, username="prog_user2")
    SessionLocal, _ = test_db

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user1.id,
            repo_url="https://github.com/gin-gonic/gin",
            status="pending",
        )
        job_id = job.id

    u2_token = create_access_token(user_id=user2.id, github_id=user2.github_id, github_username=user2.github_username)
    client.cookies.set("access_token", u2_token)

    resp = client.get(f"/progress/{job_id}")
    assert resp.status_code == 403
    assert "Access forbidden" in resp.text


def test_progress_view_renders_11_distinct_stages(client, create_user, test_db):
    """Progress view renders all 11 distinct stage cards and SSE terminal without fake telemetry."""
    user = create_user(github_id=666001, username="prog_user1")
    SessionLocal, _ = test_db

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/pallets/flask",
            status="running",
        )
        job_id = job.id

    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    resp = client.get(f"/progress/{job_id}")
    assert resp.status_code == 200
    html = resp.text

    # Header & Meta
    assert f"Job #{job_id}" in html
    assert "https://github.com/pallets/flask" in html
    assert "completed-stage-count" in html
    assert "OF 11 STAGES RESOLVED" in html

    # Verify all 11 distinct stages are present with unique keys and titles
    expected_stages = [
        ("STAGE 00", "Consent & Auth Gate", "Verified GitHub OAuth scopes"),
        ("STAGE 01", "Shallow Clone", "shallow git clone"),
        ("STAGE 02", "Discovery & File Hierarchy", "tree layout"),
        ("STAGE 03", "AST & Syntax Parsing", "concrete syntax trees"),
        ("STAGE 04", "Global Symbol Table", "function signatures"),
        ("STAGE 05", "Directed Dependency Graph", "dependency graph"),
        ("STAGE 06", "Architecture Domain Mapping", "architectural tiers"),
        ("STAGE 07", "LLM Step-by-Step Narration", "chronological reading order"),
        ("STAGE 08", "Graph & Quiz Generation", "interactive visual dependency graph"),
        ("STAGE 09", "Persistence & Architecture Report Assembly", "persisted final report"),
        ("STAGE 10", "Telemetry & Quota Allocation", "tracked AST token metrics"),
    ]

    for num, title, snippet in expected_stages:
        assert num in html
        assert title in html
        assert snippet in html

    # Real SSE Event Log Terminal is present
    assert "sse-terminal-log" in html
    assert "Live Event Stream Log" in html

    # Purged Telemetry Checks: Zero fake baud rate, packet counts, or crypto seals
    assert "baud" not in html.lower()
    assert "packet rx" not in html.lower()
    assert "packet tx" not in html.lower()
    assert "cryptographic seal" not in html.lower()
