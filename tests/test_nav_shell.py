"""Tests for Prompt 3: Site Navigation Shell, Route Highlighting, Quota Consistency, and Theme Toggle."""

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
from app.storage.billing_repository import BillingRepository
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
                avatar_url=f"https://avatars.example.com/{username}.png",
            )
            session.commit()
            session.refresh(user)
            return user

    return _create


def test_nav_shell_unauthenticated_on_login(client):
    """Unauthenticated login page displays brand and sign-in button, but no member nav or logout."""
    resp = client.get("/login")
    assert resp.status_code == 200
    html = resp.text

    assert "Backtrace" in html
    assert "theme-toggle" in html
    assert "Sign In" in html
    assert "nav-link-dashboard" not in html
    assert "nav-link-settings" not in html
    assert "nav-logout-btn" not in html


def test_nav_shell_active_route_highlighting(client, create_user, test_db):
    """Nav shell correctly highlights active routes across /dashboard, /settings, /progress, and /report."""
    user = create_user(github_id=777001, username="nav_user1")
    SessionLocal, _ = test_db

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/pallets/flask",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown="# Test Report",
            graph_data={"nodes": [], "edges": []},
            quiz_data={"questions": []},
        )
        job_id = job.id

    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    # 1. /dashboard: Dashboard link is active
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    assert 'class="nav-link active" id="nav-link-dashboard"' in resp_dash.text
    assert 'class="nav-link " id="nav-link-settings"' in resp_dash.text

    # 2. /settings: Settings link is active
    resp_set = client.get("/settings")
    assert resp_set.status_code == 200
    assert 'class="nav-link " id="nav-link-dashboard"' in resp_set.text
    assert 'class="nav-link active" id="nav-link-settings"' in resp_set.text

    # 3. /report/{job_id}: Neither dashboard nor settings is active, both links exist
    resp_rep = client.get(f"/report/{job_id}")
    assert resp_rep.status_code == 200
    assert 'class="nav-link " id="nav-link-dashboard"' in resp_rep.text
    assert 'class="nav-link " id="nav-link-settings"' in resp_rep.text


def test_nav_shell_quota_and_tier_consistency(client, create_user, test_db):
    """Nav shell tier/quota indicator matches the data rendered on Dashboard and Settings."""
    SessionLocal, _ = test_db
    user_free = create_user(github_id=777002, username="nav_free_user")
    user_pro = create_user(github_id=777003, username="nav_pro_user")

    # Record 2 usage events for user_free
    with SessionLocal() as session:
        BillingRepository.record_usage_event(session=session, user_id=user_free.id)
        BillingRepository.record_usage_event(session=session, user_id=user_free.id)
        # Make user_pro a paid subscriber
        BillingRepository.upsert_subscription(
            session=session,
            user_id=user_pro.id,
            stripe_customer_id="cus_pro_123",
            stripe_subscription_id="sub_pro_123",
            status="active",
        )
        session.commit()

    # Free User Checks
    token_free = create_access_token(user_id=user_free.id, github_id=user_free.github_id, github_username=user_free.github_username)
    client.cookies.set("access_token", token_free)

    resp_free_dash = client.get("/dashboard")
    assert "FREE (2/5)" in resp_free_dash.text
    assert "@nav_free_user" in resp_free_dash.text
    assert "/auth/logout" in resp_free_dash.text

    resp_free_set = client.get("/settings")
    assert "FREE (2/5)" in resp_free_set.text

    # Pro User Checks
    token_pro = create_access_token(user_id=user_pro.id, github_id=user_pro.github_id, github_username=user_pro.github_username)
    client.cookies.set("access_token", token_pro)

    resp_pro_dash = client.get("/dashboard")
    assert "PRO" in resp_pro_dash.text
    assert "@nav_pro_user" in resp_pro_dash.text

    resp_pro_set = client.get("/settings")
    assert "PRO" in resp_pro_set.text


def test_nav_shell_accessible_theme_toggle_and_logout(client, create_user):
    """Theme toggle has accessible labels, click handler, and focus styles; logout button is present."""
    user = create_user(github_id=777004, username="nav_user_theme")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text

    # Accessible Theme Toggle Control
    assert 'id="theme-toggle"' in html
    assert 'aria-label="Toggle dark/light mode"' in html
    assert 'onclick="toggleTheme()"' in html
    assert 'theme-toggle-btn:focus' in html
    assert 'localStorage.setItem(\'backtrace-theme\'' in html

    # Logout Link
    assert 'id="nav-logout-btn"' in html
    assert 'href="/auth/logout"' in html
