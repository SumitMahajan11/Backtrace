"""Tests for security gating of /auth/dev-login, removal of /debug/env, and open redirect defense."""

import importlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.core.config import get_settings
from app.db.session import Base
from app.models.db import UserModel
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


def test_production_environment_gates_dev_login_and_debug_env(monkeypatch):
    """In production mode, /auth/dev-login, /api/auth/dev-login, and /debug/env must return 404."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "mock_gh_client_id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "mock_gh_client_secret")
    monkeypatch.setenv("GITHUB_REDIRECT_URI", "https://app.backtrace.dev/auth/github/callback")
    monkeypatch.setenv("JWT_SECRET_KEY", "production_secret_key_at_least_32_chars_long_123456")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_mock_prod_key_123456789012345")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_mock_prod_webhook_secret_1234567890")
    monkeypatch.setenv("STRIPE_PRICE_ID_PRO", "price_mock_prod_price_id_1234567890")
    monkeypatch.setenv("DEBUG", "False")

    get_settings.cache_clear()

    import app.api.auth
    importlib.reload(app.api.auth)
    import app.main
    importlib.reload(app.main)

    with TestClient(app.main.app) as prod_client:
        r1 = prod_client.get("/auth/dev-login?user_id=1")
        assert r1.status_code == 404

        r2 = prod_client.get("/api/auth/dev-login?user_id=1")
        assert r2.status_code == 404

        r3 = prod_client.get("/debug/env")
        assert r3.status_code == 404

    # Restore settings and modules to development
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    importlib.reload(app.api.auth)
    importlib.reload(app.main)


def test_debug_env_deleted_in_development():
    """Verify /debug/env is completely removed and returns 404 even in development."""
    import app.main
    with TestClient(app.main.app) as client:
        resp = client.get("/debug/env")
        assert resp.status_code == 404


def test_debug_trigger_error_deleted():
    """Verify /debug/trigger-error is completely removed and returns 404."""
    import app.main
    with TestClient(app.main.app) as client:
        resp = client.get("/debug/trigger-error")
        assert resp.status_code == 404


def test_dev_login_open_redirect_rejected_in_development(test_db, monkeypatch):
    """In development mode, open redirect targets (absolute URLs, protocol-relative URLs) are rejected."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()

    import app.api.auth
    importlib.reload(app.api.auth)
    import app.main
    importlib.reload(app.main)

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

    app.main.app.dependency_overrides[get_db] = override_get_db

    # Create test user
    with TestingSessionLocal() as session:
        user = UserRepository.upsert_github_user(
            session=session,
            github_id=99901,
            github_username="dev_sec_user",
            email="devsec@example.com",
            avatar_url="https://example.com/avatar.png",
        )
        session.commit()
        user_id = user.id

    with TestClient(app.main.app) as dev_client:
        # 1. Reject absolute URL
        resp_evil = dev_client.get(f"/auth/dev-login?user_id={user_id}&redirect_url=https://evil.com", follow_redirects=False)
        assert resp_evil.status_code == 400
        assert "open redirect rejected" in resp_evil.json()["detail"].lower()

        # 2. Reject protocol-relative URL
        resp_proto = dev_client.get(f"/auth/dev-login?user_id={user_id}&redirect_url=//evil.com", follow_redirects=False)
        assert resp_proto.status_code == 400
        assert "open redirect rejected" in resp_proto.json()["detail"].lower()

        # 3. Reject backslash URL
        resp_slash = dev_client.get(f"/auth/dev-login?user_id={user_id}&redirect_url=/\\evil.com", follow_redirects=False)
        assert resp_slash.status_code == 400
        assert "open redirect rejected" in resp_slash.json()["detail"].lower()

        # 4. Accept valid relative path
        resp_valid = dev_client.get(f"/auth/dev-login?user_id={user_id}&redirect_url=/dashboard", follow_redirects=False)
        assert resp_valid.status_code == 302
        assert resp_valid.headers["location"] == "/dashboard"
        assert "access_token" in resp_valid.cookies

        # 5. Non-existent user returns 404
        resp_not_found = dev_client.get("/auth/dev-login?user_id=999999&redirect_url=/rewards", follow_redirects=False)
        assert resp_not_found.status_code == 404

    app.main.app.dependency_overrides.clear()
