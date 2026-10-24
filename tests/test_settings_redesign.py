"""Tests for Prompt 5: Settings & Billing Redesign, Theme Switches, and Dynamic Stripe Pricing."""

import os
import time
from datetime import datetime, timedelta, timezone
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
from app.services.billing_service import BillingService
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
                avatar_url=f"https://avatars.example.com/{username}",
            )
            session.commit()
            session.refresh(user)
            return user

    return _create


def test_settings_unauthenticated_redirect(client):
    """Unauthenticated users visiting /settings must be redirected to /login."""
    resp = client.get("/settings", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_settings_free_user_view(client, create_user, test_db, monkeypatch):
    """Free user sees identity, theme cards, free quota meter, and upgrade CTA when billing is enabled."""
    monkeypatch.setenv("STRIPE_BILLING_ENABLED", "true")
    monkeypatch.setenv("PRO_PRICE_DISPLAY", "$9 / month")
    user = create_user(github_id=777001, username="settings_user1")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.text

    # 1. Identity
    assert "@settings_user1" in html
    assert "settings_user1@example.com" in html
    assert "Institutional Identity" in html
    assert "Profile information and notification email are synced directly from GitHub OAuth" in html

    # 2. Themes
    assert "Theme" in html
    assert "Dark Architecture Report" in html
    assert "Light Archival" in html
    assert "Detect my system" in html

    # 3. Quota & Plan
    assert "FREE TIER" in html
    assert "0 / 5 CONSUMED" in html
    assert "AUTOMATIC RESET:" in html

    # 4. Price Display ($9 / month, NOT hardcoded $29)
    assert "$9 / month" in html
    assert "$29" not in html
    assert "/api/billing/checkout" in html

    # 5. Logout
    assert "/auth/logout" in html
    assert "Sign Out of Backtrace" in html


def test_settings_paid_user_view(client, create_user, test_db):
    """Paid user sees PRO TIER badge, unlimited usage, and customer portal link."""
    user = create_user(github_id=777002, username="paid_settings_user")
    SessionLocal, _ = test_db
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    future_end = datetime.now(timezone.utc) + timedelta(days=30)
    with SessionLocal() as session:
        BillingRepository.upsert_subscription(
            session=session,
            user_id=user.id,
            stripe_customer_id="cus_test_paid_settings",
            stripe_subscription_id="sub_test_paid_settings",
            status="active",
            current_period_end=future_end.replace(tzinfo=None),
        )
        session.commit()

    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.text

    assert "PRO TIER" in html
    assert "UNLIMITED ANALYSIS JOBS" in html
    assert "Manage Subscription &amp; Invoices" in html
    assert "/api/billing/portal" in html


def test_billing_service_price_retrieval_and_formatting(monkeypatch):
    """Unit test: PRO_PRICE_DISPLAY formatting without calling Stripe."""
    monkeypatch.setenv("STRIPE_BILLING_ENABLED", "true")
    monkeypatch.setenv("PRO_PRICE_DISPLAY", "$9 / month")

    with patch("stripe.Price.retrieve", side_effect=RuntimeError("Stripe should never be called")):
        res = BillingService.get_pro_price_details("price_usd_test")
        assert res["amount_formatted"] == "$9 / month"
        assert res["price_display"] == "$9 / month"
        assert res["currency"] == "usd"
        assert res["interval"] == "month"
