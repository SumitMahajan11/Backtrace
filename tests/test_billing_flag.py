"""Tests for billing flag, checkout error handling, price display, and UI card visibility."""

from unittest.mock import MagicMock, patch
import pytest
import stripe
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.core.config import billing_enabled
from app.db.session import Base
from app.main import app
from app.models.db import UserModel
from app.security.auth import create_access_token
from app.storage.user_repository import UserRepository


@pytest.fixture
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


@pytest.fixture
def auth_client(test_db):
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(
            db_session,
            github_id=8888,
            github_username="flagtester",
            email="flagtester@example.com",
        )
        db_session.commit()
        user_id = user.id

    token = create_access_token(user_id, 8888, "flagtester")
    with TestClient(app) as client:
        client.cookies.set("access_token", token)
        client.headers["Authorization"] = f"Bearer {token}"
        yield client, user_id


def test_billing_disabled_get_checkout_route(auth_client, monkeypatch):
    """billing disabled: GET checkout route returns 404 or redirect, and the Stripe client is never called."""
    client, _ = auth_client
    monkeypatch.setenv("STRIPE_BILLING_ENABLED", "false")
    assert billing_enabled() is False

    with patch("stripe.checkout.Session.create") as mock_stripe:
        response = client.get("/billing/checkout", follow_redirects=False)
        assert response.status_code in (404, 302, 303, 307)
        mock_stripe.assert_not_called()


def test_billing_enabled_stripe_error_redirects(auth_client, monkeypatch):
    """billing enabled and Stripe raises StripeError: response is a redirect to /settings?billing=error,
    body has no 'request_id', no 'req_' and no '{'.
    """
    client, _ = auth_client
    monkeypatch.setenv("STRIPE_BILLING_ENABLED", "true")
    assert billing_enabled() is True

    with patch("stripe.checkout.Session.create", side_effect=stripe.error.StripeError("Stripe API down req_abc123 request_id")):
        response = client.get("/billing/checkout", follow_redirects=False)
        assert response.status_code in (302, 303, 307)
        assert response.headers["location"].endswith("/settings?billing=error")
        body_text = response.text
        assert "request_id" not in body_text
        assert "req_" not in body_text
        assert "{" not in body_text


def test_billing_disabled_ui_hides_upgrade_to_pro(auth_client, monkeypatch):
    """billing disabled: Dashboard and Settings HTML do not contain 'Upgrade to Pro'."""
    client, _ = auth_client
    monkeypatch.setenv("STRIPE_BILLING_ENABLED", "false")
    assert billing_enabled() is False

    dash_resp = client.get("/dashboard")
    assert dash_resp.status_code == 200
    assert "Upgrade to Pro" not in dash_resp.text

    settings_resp = client.get("/settings")
    assert settings_resp.status_code == 200
    assert "Upgrade to Pro" not in settings_resp.text


def test_billing_enabled_settings_renders_price_display(auth_client, monkeypatch):
    """billing enabled: Settings HTML contains the PRO_PRICE_DISPLAY value."""
    client, _ = auth_client
    custom_price = "$19 / month"
    monkeypatch.setenv("STRIPE_BILLING_ENABLED", "true")
    monkeypatch.setenv("PRO_PRICE_DISPLAY", custom_price)
    assert billing_enabled() is True

    settings_resp = client.get("/settings")
    assert settings_resp.status_code == 200
    assert custom_price in settings_resp.text
