"""Tests for Cookie Security Flags in Authentication Endpoints.

Verifies:
- Under production (ENVIRONMENT=production), all Set-Cookie headers include 'Secure'.
- Under development (ENVIRONMENT=development), Set-Cookie headers do NOT include 'Secure'.
"""

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import _is_secure_cookie
from app.api.dependencies import get_db
from app.core.config import get_settings
from app.db.session import Base
from app.main import app
from app.services.auth_service import AuthService
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


def test_is_secure_cookie_helper(monkeypatch):
    """Verify _is_secure_cookie() returns True for production, False for development."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    assert _is_secure_cookie() is True

    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    assert _is_secure_cookie() is False


def test_refresh_endpoint_cookie_secure_in_production(client, test_db, monkeypatch):
    """
    In production mode, POST /auth/refresh returns Set-Cookie headers
    containing 'Secure' for both access_token and refresh_token.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()

    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=9876, github_username="prod_user")
        tokens = AuthService.issue_token_pair(db_session, user)
        db_session.commit()

    resp = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200

    set_cookie_headers = resp.headers.get_list("set-cookie")
    assert len(set_cookie_headers) == 2, f"Expected 2 Set-Cookie headers, got {set_cookie_headers}"

    # Both access_token and refresh_token cookies must have 'secure'
    for header in set_cookie_headers:
        assert "secure" in header.lower(), f"Expected 'Secure' attribute in Set-Cookie: {header}"


def test_refresh_endpoint_cookie_not_secure_in_development(client, test_db, monkeypatch):
    """
    In development mode, POST /auth/refresh returns Set-Cookie headers
    that do NOT contain 'Secure'.
    """
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()

    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=5432, github_username="dev_user")
        tokens = AuthService.issue_token_pair(db_session, user)
        db_session.commit()

    resp = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200

    set_cookie_headers = resp.headers.get_list("set-cookie")
    assert len(set_cookie_headers) == 2, f"Expected 2 Set-Cookie headers, got {set_cookie_headers}"

    # Neither cookie should have 'secure'
    for header in set_cookie_headers:
        assert "secure" not in header.lower(), f"Did not expect 'Secure' attribute in dev Set-Cookie: {header}"


def test_oauth_callback_cookie_secure_in_production(client, test_db, monkeypatch):
    """
    In production mode, GET /auth/github/callback sets Secure on cookies.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()

    fake_tokens = {
        "access_token": "mock_access_jwt_prod",
        "refresh_token": "mock_refresh_token_prod",
        "token_type": "bearer",
        "expires_in": 900,
        "user": {"id": 1, "github_username": "prod_user"},
    }

    with patch.object(AuthService, "process_oauth_callback", new_callable=AsyncMock, return_value=(fake_tokens, "/dashboard")):
        resp = client.get(
            "/auth/github/callback?code=mock_code&state=mock_state",
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        set_cookie_headers = resp.headers.get_list("set-cookie")
        assert len(set_cookie_headers) == 2
        for header in set_cookie_headers:
            assert "secure" in header.lower(), f"Expected Secure in callback cookie: {header}"


def test_oauth_callback_cookie_not_secure_in_development(client, test_db, monkeypatch):
    """
    In development mode, GET /auth/github/callback does NOT set Secure on cookies.
    """
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()

    fake_tokens = {
        "access_token": "mock_access_jwt_dev",
        "refresh_token": "mock_refresh_token_dev",
        "token_type": "bearer",
        "expires_in": 900,
        "user": {"id": 2, "github_username": "dev_user"},
    }

    with patch.object(AuthService, "process_oauth_callback", new_callable=AsyncMock, return_value=(fake_tokens, "/dashboard")):
        resp = client.get(
            "/auth/github/callback?code=mock_code&state=mock_state",
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        set_cookie_headers = resp.headers.get_list("set-cookie")
        assert len(set_cookie_headers) == 2
        for header in set_cookie_headers:
            assert "secure" not in header.lower(), f"Did not expect Secure in dev callback cookie: {header}"

