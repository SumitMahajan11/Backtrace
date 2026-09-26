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
        SENTRY_DSN="https://key@sentry.io/123456",
        POSTHOG_API_KEY="phc_live_key_123456",
    )

    assert settings.ENVIRONMENT == "production"
    assert settings.DEBUG is False
    assert settings.GITHUB_CLIENT_ID == "gh_prod_client_12345678"
    assert settings.STRIPE_PRICE_ID_PRO == "price_pro_monthly_tier_123"


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
