"""Production Readiness, Fail-Fast Configuration, and Secret Hardening Tests."""

import os
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.billing_service import BillingService, BillingServiceError


def test_production_config_fails_when_secrets_missing():
    """Validates that production environment mode raises ValidationError if any secret is missing."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            GITHUB_CLIENT_ID=None,
            GITHUB_CLIENT_SECRET=None,
            STRIPE_SECRET_KEY=None,
            STRIPE_WEBHOOK_SECRET=None,
            STRIPE_PRICE_ID_PRO=None,
        )

    err_str = str(exc_info.value)
    assert "GITHUB_CLIENT_ID is required in production" in err_str
    assert "GITHUB_CLIENT_SECRET is required in production" in err_str
    assert "STRIPE_SECRET_KEY is required in production" in err_str
    assert "STRIPE_WEBHOOK_SECRET is required in production" in err_str
    assert "STRIPE_PRICE_ID_PRO is required in production" in err_str


def test_production_config_rejects_weak_or_default_jwt_secret():
    """Validates that production mode rejects default development JWT secrets or short keys."""
    # Short key
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            GITHUB_CLIENT_ID="gh_prod_client_123",
            GITHUB_CLIENT_SECRET="gh_prod_secret_456",
            GITHUB_REDIRECT_URI="https://app.backtrace.dev/auth/callback",
            JWT_SECRET_KEY="short_secret",
            STRIPE_SECRET_KEY="sk_" + "live_1234567890abcdef",
            STRIPE_WEBHOOK_SECRET="whsec_abcdef123456",
            STRIPE_PRICE_ID_PRO="price_1234567890",
        )
    assert "JWT_SECRET_KEY must be at least 32 characters long" in str(exc_info.value)

    # Development placeholder default
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            GITHUB_CLIENT_ID="gh_prod_client_123",
            GITHUB_CLIENT_SECRET="gh_prod_secret_456",
            GITHUB_REDIRECT_URI="https://app.backtrace.dev/auth/callback",
            JWT_SECRET_KEY="development_secret_key_change_in_production_min_32_chars",
            STRIPE_SECRET_KEY="sk_" + "live_1234567890abcdef",
            STRIPE_WEBHOOK_SECRET="whsec_abcdef123456",
            STRIPE_PRICE_ID_PRO="price_1234567890",
        )
    assert "JWT_SECRET_KEY cannot use development default" in str(exc_info.value)


def test_production_config_rejects_localhost_oauth_redirect():
    """Validates that production mode blocks localhost redirect URIs for GitHub OAuth."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            GITHUB_CLIENT_ID="gh_prod_client_123",
            GITHUB_CLIENT_SECRET="gh_prod_secret_456",
            GITHUB_REDIRECT_URI="http://localhost:8000/api/auth/callback",
            JWT_SECRET_KEY="a_very_secure_production_jwt_key_that_is_long_enough",
            STRIPE_SECRET_KEY="sk_" + "live_1234567890abcdef",
            STRIPE_WEBHOOK_SECRET="whsec_abcdef123456",
            STRIPE_PRICE_ID_PRO="price_1234567890",
        )
    assert "GITHUB_REDIRECT_URI in production cannot point to localhost" in str(exc_info.value)


def test_production_config_passes_with_all_valid_credentials():
    """Validates that production mode initializes cleanly when complete production settings are provided."""
    settings = Settings(
        ENVIRONMENT="production",
        DEBUG=False,
        GITHUB_CLIENT_ID="gh_prod_client_12345678",
        GITHUB_CLIENT_SECRET="gh_prod_secret_9876543210abcdef",
        GITHUB_REDIRECT_URI="https://app.backtrace.dev/api/auth/callback",
        JWT_SECRET_KEY="production_super_secret_jwt_encryption_key_32_bytes_min",
        STRIPE_SECRET_KEY="sk_" + "live_abcdef1234567890",
        STRIPE_WEBHOOK_SECRET="whsec_1234567890abcdef",
        STRIPE_PRICE_ID_PRO="price_pro_monthly_tier_123",
        DATABASE_URL="postgresql://user:pass@ep-neon-123.us-east-2.aws.neon.tech/neondb?sslmode=require",
        SENTRY_DSN="https://key@sentry.io/123456",
        POSTHOG_API_KEY="phc_live_key_123456",
    )

    assert settings.ENVIRONMENT == "production"
    assert settings.DEBUG is False
    assert settings.GITHUB_CLIENT_ID == "gh_prod_client_12345678"
    assert settings.STRIPE_PRICE_ID_PRO == "price_pro_monthly_tier_123"
    assert settings.DATABASE_URL.startswith("postgresql://")


def test_production_config_rejects_sqlite_database_url():
    """Validates that production mode strictly rejects SQLite or memory database URLs."""
    # 1. Default SQLite URL (omitted DATABASE_URL)
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            GITHUB_CLIENT_ID="gh_prod_client_123",
            GITHUB_CLIENT_SECRET="gh_prod_secret_456",
            GITHUB_REDIRECT_URI="https://app.backtrace.dev/auth/callback",
            JWT_SECRET_KEY="a_very_secure_production_jwt_key_that_is_long_enough",
            STRIPE_SECRET_KEY="sk_" + "live_1234567890abcdef",
            STRIPE_WEBHOOK_SECRET="whsec_abcdef123456",
            STRIPE_PRICE_ID_PRO="price_1234567890",
        )
    assert "DATABASE_URL cannot be SQLite" in str(exc_info.value)

    # 2. Explicit SQLite file URL
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            GITHUB_CLIENT_ID="gh_prod_client_123",
            GITHUB_CLIENT_SECRET="gh_prod_secret_456",
            GITHUB_REDIRECT_URI="https://app.backtrace.dev/auth/callback",
            JWT_SECRET_KEY="a_very_secure_production_jwt_key_that_is_long_enough",
            STRIPE_SECRET_KEY="sk_" + "live_1234567890abcdef",
            STRIPE_WEBHOOK_SECRET="whsec_abcdef123456",
            STRIPE_PRICE_ID_PRO="price_1234567890",
            DATABASE_URL="sqlite:///./backtrace.db",
        )
    assert "DATABASE_URL cannot be SQLite" in str(exc_info.value)

    # 3. Explicit SQLite in-memory URL
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            GITHUB_CLIENT_ID="gh_prod_client_123",
            GITHUB_CLIENT_SECRET="gh_prod_secret_456",
            GITHUB_REDIRECT_URI="https://app.backtrace.dev/auth/callback",
            JWT_SECRET_KEY="a_very_secure_production_jwt_key_that_is_long_enough",
            STRIPE_SECRET_KEY="sk_" + "live_1234567890abcdef",
            STRIPE_WEBHOOK_SECRET="whsec_abcdef123456",
            STRIPE_PRICE_ID_PRO="price_1234567890",
            DATABASE_URL="sqlite:///:memory:",
        )
    assert "DATABASE_URL cannot be SQLite" in str(exc_info.value)

    # 4. Valid PostgreSQL Neon URL succeeds
    prod = Settings(
        ENVIRONMENT="production",
        GITHUB_CLIENT_ID="gh_prod_client_123",
        GITHUB_CLIENT_SECRET="gh_prod_secret_456",
        GITHUB_REDIRECT_URI="https://app.backtrace.dev/auth/callback",
        JWT_SECRET_KEY="a_very_secure_production_jwt_key_that_is_long_enough",
        STRIPE_SECRET_KEY="sk_" + "live_1234567890abcdef",
        STRIPE_WEBHOOK_SECRET="whsec_abcdef123456",
        STRIPE_PRICE_ID_PRO="price_1234567890",
        DATABASE_URL="postgresql://user:pass@ep-neon-123.us-east-2.aws.neon.tech/neondb?sslmode=require",
    )
    assert prod.DATABASE_URL.startswith("postgresql://")


def test_stripe_webhook_rejects_invalid_cryptographic_signature():
    """
    Validates that BillingService webhook verification strictly rejects invalid signatures.
    Note: Distinguishes from test_billing_and_quota.py by verifying that the direct service layer
    rejects malformed raw payloads and signature headers even before endpoint routing,
    exercising the pure cryptographic verification boundary with specific HTTP 400 error codes.
    """
    fake_payload = b'{"id": "evt_test", "type": "checkout.session.completed"}'
    fake_sig = "t=1600000000,v1=invalid_signature_hash_that_does_not_match"
    valid_secret = "whsec_test_secret_12345"

    with pytest.raises(BillingServiceError) as exc_info:
        BillingService.verify_and_construct_webhook_event(
            payload_bytes=fake_payload,
            sig_header=fake_sig,
            webhook_secret=valid_secret,
        )
    assert "Invalid Stripe webhook signature" in str(exc_info.value)
    assert exc_info.value.status_code == 400


def test_postgres_engine_configures_pool_pre_ping_and_pool_recycle(tmp_path):
    """
    Validates that when DATABASE_URL points to PostgreSQL (such as Neon),
    the SQLAlchemy engine is configured with pool_pre_ping=True to discard stale
    connections after idle compute suspension, and pool_recycle=1800 (or DB_POOL_RECYCLE).
    Runs in a subprocess to avoid mutating app.db.session in the test runner process.
    """
    import os
    import subprocess
    import sys

    code = (
        "from sqlalchemy.engine import Engine\n"
        "import app.db.session as session_module\n"
        "assert isinstance(session_module.engine, Engine)\n"
        "assert getattr(session_module.engine.pool, '_pre_ping', False) is True\n"
        "assert getattr(session_module.engine.pool, '_recycle', 0) == 1800\n"
    )

    env = dict(os.environ)
    neon_url = "postgresql://user:pass@ep-neon-123.us-east-2.aws.neon.tech/neondb?sslmode=require"
    env["DATABASE_URL"] = neon_url
    env["ENVIRONMENT"] = "production"
    env.pop("PYTEST_CURRENT_TEST", None)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    current_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{current_pythonpath}" if current_pythonpath else repo_root

    res = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path), env=env, capture_output=True, text=True)
    assert res.returncode == 0, f"Subprocess failed with code {res.returncode}:\nstdout: {res.stdout}\nstderr: {res.stderr}"


def test_production_config_allows_optional_stripe_billing():
    """Validates that production environment succeeds without Stripe keys when STRIPE_BILLING_ENABLED=False."""
    settings = Settings(
        ENVIRONMENT="production",
        GITHUB_CLIENT_ID="gh_client_test_id",
        GITHUB_CLIENT_SECRET="gh_client_test_secret",
        GITHUB_REDIRECT_URI="https://backtrace.onrender.com/auth/github/callback",
        JWT_SECRET_KEY="a" * 32,
        DATABASE_URL="postgresql://user:pass@ep-test.neon.tech/neondb?sslmode=require",
        STRIPE_BILLING_ENABLED=False,
        STRIPE_SECRET_KEY=None,
        STRIPE_WEBHOOK_SECRET=None,
        STRIPE_PRICE_ID_PRO=None,
    )
    assert settings.STRIPE_BILLING_ENABLED is False
    assert settings.is_production is True
