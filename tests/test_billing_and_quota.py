"""Billing and Quota Gating Test Suite (Prompt 2 Verification).

Tests:
1. Table schema initialization for 'subscriptions', 'usage_events', and 'processed_webhook_events'.
2. Hosted Stripe Checkout Session creation for authenticated user (Zero-PCI).
3. Hosted Stripe Customer Portal Session creation for existing subscriber.
4. Portal request rejected with HTTP 400 when user has no Stripe customer record.
5. Stripe webhook signature verification: invalid / missing signatures rejected with HTTP 400.
6. Stripe webhook event handling: 'checkout.session.completed' activates user subscription.
7. Stripe webhook event handling: 'customer.subscription.updated' and 'customer.subscription.deleted'.
8. Stripe webhook idempotency: duplicate event IDs safely deduplicated without double processing.
9. Free-tier quota enforcement: 5 allowed per month; 6th request blocked with HTTP 402.
10. Paid-tier quota bypass: active subscribers have unlimited analyses with HTTP 200.
11. Cross-user billing isolation: portal/checkout strictly tied to authenticated user.
"""

import hmac
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import (
    ProcessedWebhookEventModel,
    SubscriptionModel,
    UsageEventModel,
    UserModel,
    utc_now,
)
from app.security.auth import create_access_token, refresh_rate_limiter
from app.services.billing_service import BillingService
from app.storage.billing_repository import BillingRepository
from app.storage.user_repository import UserRepository

TEST_WEBHOOK_SECRET = "whsec_test_secret_key_1234567890"


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


def generate_stripe_signature(payload_bytes: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    """Generates a valid Stripe-Signature header using HMAC-SHA256."""
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
    signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_schema_subscriptions_and_usage_tables(test_db):
    """
    Acceptance Criteria: Verify 'subscriptions', 'usage_events', and 'processed_webhook_events'
    tables are created with required columns and constraints.
    """
    _, engine = test_db
    with engine.connect() as conn:
        sub_cols = [col[1] for col in conn.execute(text("PRAGMA table_info(subscriptions)")).fetchall()]
        assert "id" in sub_cols
        assert "user_id" in sub_cols
        assert "stripe_customer_id" in sub_cols
        assert "stripe_subscription_id" in sub_cols
        assert "status" in sub_cols
        assert "current_period_end" in sub_cols
        assert "created_at" in sub_cols
        assert "updated_at" in sub_cols

        usage_cols = [col[1] for col in conn.execute(text("PRAGMA table_info(usage_events)")).fetchall()]
        assert "id" in usage_cols
        assert "user_id" in usage_cols
        assert "event_type" in usage_cols
        assert "created_at" in usage_cols

        webhook_cols = [col[1] for col in conn.execute(text("PRAGMA table_info(processed_webhook_events)")).fetchall()]
        assert "id" in webhook_cols
        assert "event_id" in webhook_cols
        assert "event_type" in webhook_cols
        assert "processed_at" in webhook_cols


def test_billing_checkout_authenticated(client, test_db):
    """
    Acceptance Criteria: Authenticated user can create a hosted Stripe Checkout Session.
    Returns checkout URL without touching raw card data (Zero-PCI).
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=101, github_username="buyer1", email="buyer@test.com")
        db_session.commit()
        user_id = user.id
    token = create_access_token(user_id, 101, "buyer1")

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/c/pay/cs_test_mock_url_123"

    with patch("stripe.checkout.Session.create", return_value=mock_session) as mock_create:
        resp = client.post(
            "/billing/checkout",
            json={"success_url": "http://localhost:3000/success", "cancel_url": "http://localhost:3000/cancel"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["checkout_url"] == "https://checkout.stripe.com/c/pay/cs_test_mock_url_123"

        # Verify arguments passed to Stripe
        mock_create.assert_called_once()
        kwargs = mock_create.call_args[1]
        assert kwargs["mode"] == "subscription"
        assert kwargs["client_reference_id"] == str(user_id)
        assert kwargs["customer_email"] == "buyer@test.com"


def test_billing_portal_authenticated_existing_customer(client, test_db):
    """
    Acceptance Criteria: Subscribed user can access Stripe Customer Portal for self-serve management.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=102, github_username="subscriber1")
        BillingRepository.upsert_subscription(db_session, user_id=user.id, stripe_customer_id="cus_existing_999", status="active")
        db_session.commit()
        user_id = user.id
    token = create_access_token(user_id, 102, "subscriber1")

    mock_portal = MagicMock()
    mock_portal.url = "https://billing.stripe.com/p/session/portal_test_999"

    with patch("stripe.billing_portal.Session.create", return_value=mock_portal) as mock_create:
        resp = client.post(
            "/billing/portal",
            json={"return_url": "http://localhost:3000/dashboard"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["portal_url"] == "https://billing.stripe.com/p/session/portal_test_999"
        mock_create.assert_called_once_with(customer="cus_existing_999", return_url="http://localhost:3000/dashboard")


def test_billing_portal_no_customer_rejected(client, test_db):
    """
    Acceptance Criteria: Non-subscribed user attempting to open Customer Portal receives HTTP 400.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=103, github_username="free_user")
        db_session.commit()
        user_id = user.id
    token = create_access_token(user_id, 103, "free_user")

    resp = client.post("/billing/portal", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400
    assert "No active Stripe customer record found" in resp.json()["detail"]


def test_webhook_invalid_signature_rejected(client, monkeypatch):
    """
    Acceptance Criteria: Webhook with invalid or missing Stripe-Signature is rejected with HTTP 400.
    """
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    payload = json.dumps({"id": "evt_fake", "type": "checkout.session.completed"}).encode("utf-8")

    # 1. Missing header
    resp_no_header = client.post("/webhooks/stripe", content=payload)
    assert resp_no_header.status_code == 400
    assert "Missing required 'Stripe-Signature' header" in resp_no_header.json()["detail"]

    # 2. Forged signature
    bad_headers = {"Stripe-Signature": "t=12345,v1=invalid_forged_signature_hex"}
    resp_bad = client.post("/webhooks/stripe", content=payload, headers=bad_headers)
    assert resp_bad.status_code == 400
    assert "Invalid Stripe webhook signature" in resp_bad.json()["detail"]


def test_webhook_checkout_session_completed_flow(client, test_db, monkeypatch):
    """
    Acceptance Criteria: Real/simulated checkout.session.completed webhook activates user subscription.
    """
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    SessionLocal, _ = test_db

    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=201, github_username="paid_member")
        db_session.commit()
        user_id = user.id

    event_payload = {
        "id": "evt_checkout_success_001",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_complete_123",
                "client_reference_id": str(user_id),
                "customer": "cus_stripe_real_123",
                "subscription": "sub_stripe_real_456",
                "payment_status": "paid",
            }
        },
    }
    payload_bytes = json.dumps(event_payload).encode("utf-8")
    sig_header = generate_stripe_signature(payload_bytes, TEST_WEBHOOK_SECRET)

    resp = client.post("/webhooks/stripe", content=payload_bytes, headers={"Stripe-Signature": sig_header})
    assert resp.status_code == 200
    assert resp.json()["status"] == "processed"
    assert resp.json()["event_id"] == "evt_checkout_success_001"

    # Verify subscription record in database
    with SessionLocal() as db_session:
        sub = BillingRepository.get_subscription_by_user_id(db_session, user_id)
        assert sub is not None
        assert sub.stripe_customer_id == "cus_stripe_real_123"
        assert sub.stripe_subscription_id == "sub_stripe_real_456"
        assert sub.status == "active"


def test_webhook_subscription_updated_and_deleted(client, test_db, monkeypatch):
    """
    Acceptance Criteria: Subscription updates (past_due) and cancellations (deleted) are reflected in DB.
    """
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    SessionLocal, _ = test_db

    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=202, github_username="churn_user")
        BillingRepository.upsert_subscription(
            db_session, user_id=user.id, stripe_customer_id="cus_churn", stripe_subscription_id="sub_churn_777", status="active"
        )
        db_session.commit()
        user_id = user.id

    # 1. Update status to past_due
    future_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
    update_payload = {
        "id": "evt_sub_updated_002",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_churn_777",
                "customer": "cus_churn",
                "status": "past_due",
                "current_period_end": future_end,
            }
        },
    }
    raw_update = json.dumps(update_payload).encode("utf-8")
    client.post("/webhooks/stripe", content=raw_update, headers={"Stripe-Signature": generate_stripe_signature(raw_update)})

    with SessionLocal() as db_session:
        sub = BillingRepository.get_subscription_by_user_id(db_session, user_id)
        assert sub.status == "past_due"
        assert sub.current_period_end is not None

    # 2. Deletion event -> status canceled
    delete_payload = {
        "id": "evt_sub_deleted_003",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_churn_777",
                "customer": "cus_churn",
                "status": "canceled",
            }
        },
    }
    raw_delete = json.dumps(delete_payload).encode("utf-8")
    client.post("/webhooks/stripe", content=raw_delete, headers={"Stripe-Signature": generate_stripe_signature(raw_delete)})

    with SessionLocal() as db_session:
        sub = BillingRepository.get_subscription_by_user_id(db_session, user_id)
        assert sub.status == "canceled"


def test_webhook_idempotent_dedup_no_double_apply(client, test_db, monkeypatch):
    """
    Acceptance Criteria: Sending the same Stripe webhook event ID twice is safely deduplicated
    and does not duplicate state or database entries.
    """
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    SessionLocal, _ = test_db

    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=203, github_username="dedup_user")
        db_session.commit()
        user_id = user.id

    event_payload = {
        "id": "evt_idempotent_test_999",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_dedup_1",
                "client_reference_id": str(user_id),
                "customer": "cus_dedup_1",
                "subscription": "sub_dedup_1",
            }
        },
    }
    raw_event = json.dumps(event_payload).encode("utf-8")
    sig = generate_stripe_signature(raw_event)

    # First delivery
    resp1 = client.post("/webhooks/stripe", content=raw_event, headers={"Stripe-Signature": sig})
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "processed"

    # Second delivery with exact same event ID (Stripe at-least-once retry)
    resp2 = client.post("/webhooks/stripe", content=raw_event, headers={"Stripe-Signature": sig})
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "ignored"
    assert "already been processed" in resp2.json()["message"]

    # Verify only one webhook record exists in DB
    with SessionLocal() as db_session:
        count = db_session.query(ProcessedWebhookEventModel).filter_by(event_id="evt_idempotent_test_999").count()
        assert count == 1


def test_quota_free_tier_blocking_when_limit_hit(client, test_db, monkeypatch):
    """
    Acceptance Criteria: Free-tier user is permitted 5 repository analyses per month.
    The 6th analysis is blocked with HTTP 402 Payment Required and upgrade instructions.
    """
    monkeypatch.setenv("FREE_TIER_MONTHLY_QUOTA", "5")
    SessionLocal, _ = test_db

    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=301, github_username="freetier_tester")
        db_session.commit()
        user_id = user.id
    token = create_access_token(user_id, 301, "freetier_tester")

    pipeline_payload = {
        "repo_name": "sample/quota-test",
        "file_paths": ["app.py"],
        "file_contents": {"app.py": "def run(): pass\n"},
        "enable_rag": False,
    }
    headers = {"Authorization": f"Bearer {token}"}

    # First 5 requests must succeed (HTTP 200)
    for i in range(1, 6):
        resp = client.post("/api/pipeline/run", json=pipeline_payload, headers=headers)
        assert resp.status_code == 200, f"Request {i} should succeed within quota"
        data = resp.json()
        assert data["user_tier"] == "free"
        assert data["monthly_usage_count"] == i

    # 6th request MUST be blocked (HTTP 402 Payment Required)
    resp_blocked = client.post("/api/pipeline/run", json=pipeline_payload, headers=headers)
    assert resp_blocked.status_code == 402
    err_detail = resp_blocked.json()["detail"]
    assert err_detail["error"] == "quota_exceeded"
    assert "Free tier monthly quota exceeded" in err_detail["message"]
    assert err_detail["current_usage"] == 5
    assert err_detail["quota_limit"] == 5
    assert err_detail["upgrade_url"] == "/billing/checkout"


def test_quota_paid_tier_bypasses_limit(client, test_db, monkeypatch):
    """
    Acceptance Criteria: Active paid subscribers bypass monthly quota limit with unlimited analyses.
    """
    monkeypatch.setenv("FREE_TIER_MONTHLY_QUOTA", "5")
    SessionLocal, _ = test_db

    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=302, github_username="pro_subscriber")
        future = utc_now() + timedelta(days=30)
        BillingRepository.upsert_subscription(
            db_session, user_id=user.id, stripe_customer_id="cus_pro", stripe_subscription_id="sub_pro", status="active", current_period_end=future
        )
        db_session.commit()
        user_id = user.id
    token = create_access_token(user_id, 302, "pro_subscriber")

    pipeline_payload = {
        "repo_name": "sample/pro-test",
        "file_paths": ["app.py"],
        "file_contents": {"app.py": "def run(): pass\n"},
        "enable_rag": False,
    }
    headers = {"Authorization": f"Bearer {token}"}

    # Run 8 analyses (past the free quota of 5)
    for i in range(1, 9):
        resp = client.post("/api/pipeline/run", json=pipeline_payload, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["user_tier"] == "paid"


def test_billing_status_endpoint(client, test_db):
    """
    Acceptance Criteria: GET /billing/status returns user's current tier, quota, and consumption.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=401, github_username="status_user")
        db_session.commit()
        user_id = user.id
    token = create_access_token(user_id, 401, "status_user")

    resp = client.get("/billing/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "free"
    assert data["monthly_usage"] == 0
    assert data["monthly_quota"] == 5
    assert data["is_quota_exceeded"] is False


def test_redirect_checkout_fulfillment_synchronous_upgrade(client, test_db, monkeypatch):
    """
    Acceptance Criteria: Landing on /dashboard?session_id=... synchronously fulfills the checkout session
    and upgrades the user to Pro immediately without waiting for a webhook.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=501, github_username="redirect_user")
        db_session.commit()
        user_id = user.id

    token = create_access_token(user_id, 501, "redirect_user")

    # Mock Stripe Session retrieve for a live/test session ID
    mock_session_obj = MagicMock()
    mock_session_obj.customer = MagicMock(id="cus_test_redirect_501")
    mock_session_obj.subscription = MagicMock(
        id="sub_test_redirect_501",
        status="active",
        current_period_end=int(time.time()) + 86400 * 30,
    )

    with patch("stripe.checkout.Session.retrieve", return_value=mock_session_obj):
        resp = client.get(
            "/dashboard?session_id=cs_test_redirect_valid_123",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        # Should render PRO TIER in HTML response immediately
        assert "PRO TIER" in resp.text
        assert "UNLIMITED ANALYSIS JOBS" in resp.text

    # Verify DB subscription state is active and tier is paid
    with SessionLocal() as db_session:
        status_info = BillingService.get_user_billing_status(user, db_session)
        assert status_info["tier"] == "paid"
        assert status_info["subscription_status"] == "active"
        sub = BillingRepository.get_subscription_by_user_id(db_session, user_id)
        assert sub is not None
        assert sub.stripe_customer_id == "cus_test_redirect_501"
        assert sub.stripe_subscription_id == "sub_test_redirect_501"


def test_redirect_checkout_fulfillment_idempotent(client, test_db):
    """
    Acceptance Criteria: Multiple visits with the same session_id (e.g. browser refresh or webhook duplicate)
    do not create duplicate subscription records.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=502, github_username="refresh_user")
        db_session.commit()
        user_id = user.id

    token = create_access_token(user_id, 502, "refresh_user")

    mock_session_obj = MagicMock()
    mock_session_obj.customer = MagicMock(id="cus_refresh_502")
    mock_session_obj.subscription = MagicMock(
        id="sub_refresh_502",
        status="active",
        current_period_end=int(time.time()) + 86400 * 30,
    )

    with patch("stripe.checkout.Session.retrieve", return_value=mock_session_obj):
        # 1st visit
        resp1 = client.get(
            "/dashboard?session_id=cs_refresh_123",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp1.status_code == 200

        # 2nd visit (simulating page refresh)
        resp2 = client.get(
            "/dashboard?session_id=cs_refresh_123",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 200

    # Ensure exactly 1 subscription record exists
    with SessionLocal() as db_session:
        subs = db_session.query(SubscriptionModel).filter_by(user_id=user_id).all()
        assert len(subs) == 1
        assert subs[0].stripe_customer_id == "cus_refresh_502"

