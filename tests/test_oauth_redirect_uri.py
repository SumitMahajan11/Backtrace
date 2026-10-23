"""Regression test suite for GitHub OAuth redirect URI configuration and security.

Verifies:
1. Local development login generates the correct callback URL (http://localhost:8000/auth/github/callback).
2. Production configuration retains the Render callback (https://backtrace-pbsk.onrender.com/auth/github/callback).
3. Production configuration validation rejects localhost or 127.0.0.1 callbacks.
4. GITHUB_FRONTEND_REDIRECT_URI is recognized as a valid fallback for GITHUB_REDIRECT_URI.
5. The callback endpoint remains correctly registered and processes OAuth returns.
6. Open redirect defenses reject untrusted redirect targets while accepting trusted local/production targets.
"""

import os
from unittest.mock import AsyncMock, patch
import urllib.parse
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.core.config import Settings
from app.db.session import Base
from app.main import app
from app.security.auth import is_safe_redirect_url, oauth_state_store, refresh_rate_limiter
from app.services.auth_service import AuthService, AuthServiceError


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
    yield TestingSessionLocal, engine
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def client(test_db):
    refresh_rate_limiter.reset()
    with TestClient(app) as test_client:
        yield test_client
    refresh_rate_limiter.reset()


# 1. Local login generates the correct callback URL
def test_local_login_generates_correct_callback_url(client):
    """Verifies local development initiates OAuth with http://localhost:8000/auth/github/callback."""
    with patch.dict(os.environ, {
        "ENVIRONMENT": "development",
        "GITHUB_CLIENT_ID": "gh_local_client_id",
        "GITHUB_REDIRECT_URI": "http://localhost:8000/auth/github/callback",
    }, clear=False):
        resp = client.get("/auth/github/login", follow_redirects=False)
        assert resp.status_code == 307
        location = resp.headers["location"]
        parsed = urllib.parse.urlparse(location)
        query = urllib.parse.parse_qs(parsed.query)

        assert parsed.netloc == "github.com"
        assert parsed.path == "/login/oauth/authorize"
        assert query["client_id"] == ["gh_local_client_id"]
        assert query["redirect_uri"] == ["http://localhost:8000/auth/github/callback"]
        assert "state" in query
        assert query["scope"] == ["read:user user:email"]


def test_local_login_default_fallback_without_env_var():
    """Verifies AuthService defaults to http://localhost:8000/auth/github/callback when unset."""
    with patch.dict(os.environ, {}, clear=True):
        url = AuthService.get_login_redirect_url(client_id="test_id")
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        assert query["redirect_uri"] == ["http://localhost:8000/auth/github/callback"]


# 2. Production configuration retains the Render callback
def test_production_configuration_retains_render_callback(client):
    """Verifies production retains https://backtrace-pbsk.onrender.com/auth/github/callback."""
    render_callback = "https://backtrace-pbsk.onrender.com/auth/github/callback"
    with patch.dict(os.environ, {
        "ENVIRONMENT": "production",
        "GITHUB_CLIENT_ID": "gh_prod_client_id",
        "GITHUB_REDIRECT_URI": render_callback,
    }, clear=False):
        resp = client.get("/auth/github/login", follow_redirects=False)
        assert resp.status_code == 307
        location = resp.headers["location"]
        parsed = urllib.parse.urlparse(location)
        query = urllib.parse.parse_qs(parsed.query)

        assert query["client_id"] == ["gh_prod_client_id"]
        assert query["redirect_uri"] == [render_callback]


def test_production_validation_rejects_localhost_and_127():
    """Verifies production fails fast if redirect_uri points to localhost or 127.0.0.1."""
    # Localhost in production
    with pytest.raises(ValueError, match="GITHUB_REDIRECT_URI in production cannot point to localhost"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="a" * 32,
            GITHUB_CLIENT_ID="id",
            GITHUB_CLIENT_SECRET="secret",
            GITHUB_REDIRECT_URI="http://localhost:8000/auth/github/callback",
            STRIPE_SECRET_KEY="sk_test_123",
            STRIPE_WEBHOOK_SECRET="whsec_123",
            STRIPE_PRICE_ID_PRO="price_123",
            DEBUG=False,
        )

    # 127.0.0.1 in production
    with pytest.raises(ValueError, match="GITHUB_REDIRECT_URI in production cannot point to localhost or 127.0.0.1"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="a" * 32,
            GITHUB_CLIENT_ID="id",
            GITHUB_CLIENT_SECRET="secret",
            GITHUB_REDIRECT_URI="http://127.0.0.1:8000/auth/github/callback",
            STRIPE_SECRET_KEY="sk_test_123",
            STRIPE_WEBHOOK_SECRET="whsec_123",
            STRIPE_PRICE_ID_PRO="price_123",
            DEBUG=False,
        )


def test_production_validation_rejects_placeholder_hosts():
    """Verifies production fails fast if redirect_uri points to placeholder hosts (yourdomain.com, example.com)."""
    for placeholder in [
        "https://yourdomain.com/auth/github/callback",
        "https://example.com/callback",
        "https://app.yourdomain.com/auth/callback",
        "https://api.EXAMPLE.COM/callback",
    ]:
        with pytest.raises(ValueError, match="GITHUB_REDIRECT_URI in production cannot point to placeholder domain"):
            Settings(
                ENVIRONMENT="production",
                JWT_SECRET_KEY="a" * 32,
                GITHUB_CLIENT_ID="id",
                GITHUB_CLIENT_SECRET="secret",
                GITHUB_REDIRECT_URI=placeholder,
                STRIPE_SECRET_KEY="sk_test_123",
                STRIPE_WEBHOOK_SECRET="whsec_123",
                STRIPE_PRICE_ID_PRO="price_123",
                DEBUG=False,
            )


def test_production_accepts_non_placeholder_custom_domains():
    """
    Verifies that production accepts custom domains such as 'myexample.com' (preventing false-positive substring matches),
    while rejecting 'api.yourdomain.com' and 'example.com', and verifying fallback support.
    """
    valid_uri = "https://myexample.com/cb"
    s = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a" * 32,
        GITHUB_CLIENT_ID="id",
        GITHUB_CLIENT_SECRET="secret",
        GITHUB_REDIRECT_URI=valid_uri,
        STRIPE_SECRET_KEY="sk_test_123",
        STRIPE_WEBHOOK_SECRET="whsec_123",
        STRIPE_PRICE_ID_PRO="price_123",
        DATABASE_URL="postgresql://user:pass@ep-neon-123.us-east-2.aws.neon.tech/neondb?sslmode=require",
        DEBUG=False,
    )
    assert s.GITHUB_REDIRECT_URI == valid_uri

    for rejected_uri in ["https://api.yourdomain.com/cb", "https://example.com/cb"]:
        with pytest.raises(ValueError, match="GITHUB_REDIRECT_URI in production cannot point to placeholder domain"):
            Settings(
                ENVIRONMENT="production",
                JWT_SECRET_KEY="a" * 32,
                GITHUB_CLIENT_ID="id",
                GITHUB_CLIENT_SECRET="secret",
                GITHUB_REDIRECT_URI=rejected_uri,
                STRIPE_SECRET_KEY="sk_test_123",
                STRIPE_WEBHOOK_SECRET="whsec_123",
                STRIPE_PRICE_ID_PRO="price_123",
                DEBUG=False,
            )

    # Verify fallback from GITHUB_FRONTEND_REDIRECT_URI with valid custom domain
    s_fallback = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a" * 32,
        GITHUB_CLIENT_ID="id",
        GITHUB_CLIENT_SECRET="secret",
        GITHUB_FRONTEND_REDIRECT_URI="https://myexample.com/cb",
        STRIPE_SECRET_KEY="sk_test_123",
        STRIPE_WEBHOOK_SECRET="whsec_123",
        STRIPE_PRICE_ID_PRO="price_123",
        DATABASE_URL="postgresql://user:pass@ep-neon-123.us-east-2.aws.neon.tech/neondb?sslmode=require",
        DEBUG=False,
    )
    assert s_fallback.GITHUB_REDIRECT_URI == "https://myexample.com/cb"


def test_production_accepts_render_callback_and_supports_frontend_redirect_alias():
    """Verifies production accepts Render callback and supports GITHUB_FRONTEND_REDIRECT_URI."""
    render_callback = "https://backtrace-pbsk.onrender.com/auth/github/callback"
    s = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a" * 32,
        GITHUB_CLIENT_ID="id",
        GITHUB_CLIENT_SECRET="secret",
        GITHUB_REDIRECT_URI=render_callback,
        STRIPE_SECRET_KEY="sk_test_123",
        STRIPE_WEBHOOK_SECRET="whsec_123",
        STRIPE_PRICE_ID_PRO="price_123",
        DATABASE_URL="postgresql://user:pass@ep-neon-123.us-east-2.aws.neon.tech/neondb?sslmode=require",
        DEBUG=False,
    )
    assert s.GITHUB_REDIRECT_URI == render_callback

    # When GITHUB_FRONTEND_REDIRECT_URI is provided and GITHUB_REDIRECT_URI is default
    s_alias = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a" * 32,
        GITHUB_CLIENT_ID="id",
        GITHUB_CLIENT_SECRET="secret",
        GITHUB_FRONTEND_REDIRECT_URI=render_callback,
        STRIPE_SECRET_KEY="sk_test_123",
        STRIPE_WEBHOOK_SECRET="whsec_123",
        STRIPE_PRICE_ID_PRO="price_123",
        DATABASE_URL="postgresql://user:pass@ep-neon-123.us-east-2.aws.neon.tech/neondb?sslmode=require",
        DEBUG=False,
    )
    assert s_alias.GITHUB_REDIRECT_URI == render_callback


# 3. The callback endpoint remains correctly registered
def test_callback_endpoint_registration_and_error_handling(client):
    """Verifies /auth/github/callback handles GitHub errors and missing params."""
    # GitHub returned error parameter (e.g. user cancelled)
    resp_err = client.get("/auth/github/callback?error=access_denied&error_description=The+user+has+denied+your+application")
    assert resp_err.status_code == 400
    assert "The user has denied your application" in resp_err.json()["detail"]

    # Missing state parameter
    resp_no_state = client.get("/auth/github/callback?code=mock_code")
    assert resp_no_state.status_code == 400
    assert "Missing required OAuth parameters" in resp_no_state.json()["detail"]


def test_callback_flow_preserves_registered_callback_for_token_exchange(client):
    """Verifies token exchange receives the matching callback URI used during authorization."""
    state = oauth_state_store.generate_state(
        redirect_url="/dashboard",
        callback_uri="http://localhost:8000/auth/github/callback",
    )
    mock_profile = {
        "github_id": 555666,
        "github_username": "local_dev_user",
        "email": "dev@local.test",
        "avatar_url": "https://avatars.example.com/u/555666",
    }

    with patch.object(AuthService, "exchange_github_code_async", new=AsyncMock(return_value="gho_mock_access")) as mock_exchange, \
         patch.object(AuthService, "fetch_github_user_profile_async", new=AsyncMock(return_value=mock_profile)):

        resp = client.get(f"/auth/github/callback?code=test_gh_code&state={state}")
        assert resp.status_code == 200
        mock_exchange.assert_called_once_with("test_gh_code", redirect_uri="http://localhost:8000/auth/github/callback")


# 4. Invalid or untrusted redirect targets remain rejected
def test_open_redirect_protection_in_login_and_validator(client):
    """Verifies untrusted destinations are rejected and trusted destinations accepted."""
    # Attack payloads rejected
    assert is_safe_redirect_url("https://evil.com") is False
    assert is_safe_redirect_url("https://evil.com/phishing") is False
    assert is_safe_redirect_url("//evil.com") is False
    assert is_safe_redirect_url("javascript:alert(1)") is False
    assert is_safe_redirect_url("data:text/html,<script>") is False

    # Trusted destinations accepted
    assert is_safe_redirect_url("/dashboard") is True
    assert is_safe_redirect_url("/app") is True
    assert is_safe_redirect_url("http://localhost:8000/dashboard") is True
    assert is_safe_redirect_url("http://127.0.0.1:8000/dashboard") is True
    assert is_safe_redirect_url("https://backtrace-pbsk.onrender.com/dashboard") is True

    # Untrusted destination via GET /auth/github/login returns HTTP 400
    resp_bad = client.get("/auth/github/login?redirect_url=https://evil.com")
    assert resp_bad.status_code == 400
    assert "Invalid or untrusted redirect target URL" in resp_bad.json()["detail"]

    # Trusted destination via GET /auth/github/login proceeds with HTTP 307
    resp_good = client.get("/auth/github/login?redirect_url=/dashboard", follow_redirects=False)
    assert resp_good.status_code == 307
