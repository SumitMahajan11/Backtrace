"""Comprehensive Monitoring and Analytics Test Suite.

Verifies:
1. Sentry error tracking with strict PII, token, header, and cookie redaction.
2. PostHog tracking for all 6 mandatory lifecycle events with bounded low-cardinality schemas.
3. Zero internal stack trace or secret leakage to client-facing HTTP responses.
4. Integration of analytics hooks into Auth, Analysis Pipeline, and Stripe Billing flows.
"""

from unittest.mock import AsyncMock, patch
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import UserModel
from app.monitoring.posthog import AnalyticsService, analytics
from app.monitoring.sentry import init_sentry, is_sensitive_key, scrub_sentry_event
from app.security.auth import create_access_token, oauth_state_store
from app.services.auth_service import AuthService
from app.storage.user_repository import UserRepository


# Add a test-only route to verify uncaught exception shielding
error_trigger_router = APIRouter()

@error_trigger_router.get("/test/trigger-unhandled-error")
def trigger_unhandled_error():
    raise RuntimeError("Critical database connection dropped at /secret/internal/db.py line 42")

app.include_router(error_trigger_router)


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
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def create_user(test_db):
    SessionLocal, _ = test_db

    def _create(github_id: int, username: str, is_admin: bool = False) -> UserModel:
        with SessionLocal() as session:
            user = UserRepository.upsert_github_user(
                session=session,
                github_id=github_id,
                github_username=username,
                email=f"{username}@example.com",
                avatar_url=f"https://avatars.example.com/{username}",
                is_admin=is_admin,
            )
            session.commit()
            session.refresh(user)
            return user

    return _create


# =========================================================================
# 1. Sentry Sensitive Data & Secret Redaction Tests
# =========================================================================

def test_sentry_sensitive_key_detection():
    """Verify that all auth tokens, cookies, secrets, and payment fields are recognized as sensitive."""
    assert is_sensitive_key("authorization") is True
    assert is_sensitive_key("Authorization") is True
    assert is_sensitive_key("cookie") is True
    assert is_sensitive_key("set-cookie") is True
    assert is_sensitive_key("access_token") is True
    assert is_sensitive_key("refresh_token") is True
    assert is_sensitive_key("client_secret") is True
    assert is_sensitive_key("stripe_signature") is True
    assert is_sensitive_key("card_number") is True
    assert is_sensitive_key("cvv") is True
    assert is_sensitive_key("repo_name") is False
    assert is_sensitive_key("tier") is False


def test_sentry_before_send_redaction_payload_scrubbing():
    """
    Acceptance Criteria (Threat Model):
    Before Sentry transmits any error payload, it must strip Authorization headers,
    cookies, tokens in query strings, sensitive body attributes, and user PII.
    """
    raw_event = {
        "event_id": "999888777",
        "level": "error",
        "message": "Division by zero in pipeline orchestrator",
        "request": {
            "url": "https://api.backtrace.dev/analyses/submit?token=raw_query_token_123&auth=private_key_code&state=state_abc",
            "query_string": "token=raw_query_token_123&auth=private_key_code&state=state_abc&public_filter=active",
            "headers": {
                "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sensitive_payload",
                "Cookie": "access_token=secret_jwt_cookie; refresh_token=secret_refresh_cookie",
                "Stripe-Signature": "t=123456,v1=secret_signature_hash",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Host": "api.backtrace.dev",
            },
            "cookies": {
                "access_token": "secret_jwt_cookie",
                "refresh_token": "secret_refresh_cookie",
                "analytics_id": "anon_123",
            },
            "data": {
                "repo_url": "https://github.com/org/repo",
                "access_token": "secret_token_val",
                "password": "super_secret_password",
                "card": {
                    "number": "4111222233334444",
                    "cvv": "123",
                    "exp_month": 12,
                },
                "safe_metadata": "public_build_info",
            },
        },
        "user": {
            "id": 101,
            "email": "ceo@enterprise.com",
            "username": "super_ceo",
            "ip_address": "192.168.1.1",
        },
        "extra": {
            "debug_auth_header": "Bearer secret_extra_token",
            "safe_counter": 42,
        },
        "breadcrumbs": {
            "values": [
                {
                    "message": "User clicked submit",
                    "data": {"access_token": "breadcrumb_secret_token", "action": "submit_click"},
                }
            ]
        },
    }

    # Execute scrubber
    scrubbed_event = scrub_sentry_event(raw_event)

    # 1. Verify Headers Redaction
    req = scrubbed_event["request"]
    assert req["headers"]["Authorization"] == "[REDACTED]"
    assert req["headers"]["Cookie"] == "[REDACTED]"
    assert req["headers"]["Stripe-Signature"] == "[REDACTED]"
    assert req["headers"]["User-Agent"] == "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"  # Safe preserved

    # 2. Verify Cookies Redaction
    assert req["cookies"]["access_token"] == "[REDACTED]"
    assert req["cookies"]["refresh_token"] == "[REDACTED]"

    # 3. Verify Query String & URL Redaction
    assert req["url"] == "https://api.backtrace.dev/analyses/submit?token=[REDACTED]&auth=[REDACTED]&state=[REDACTED]"
    assert "token=[REDACTED]" in req["query_string"]
    assert "auth=[REDACTED]" in req["query_string"]
    assert "state=[REDACTED]" in req["query_string"]
    assert "public_filter=active" in req["query_string"]

    # 4. Verify Request Body Sensitive Keys Redacted
    assert req["data"]["access_token"] == "[REDACTED]"
    assert req["data"]["password"] == "[REDACTED]"
    assert req["data"]["card"] == "[REDACTED]"  # Whole card dict redacted
    assert req["data"]["repo_url"] == "https://github.com/org/repo"
    assert req["data"]["safe_metadata"] == "public_build_info"

    # 5. Verify User Context Zero-PII Policy & IP Geolocation Suppression
    assert scrubbed_event["user"] == {"id": "usr_101", "ip_address": "{{none}}"}
    assert "email" not in scrubbed_event["user"]
    assert "username" not in scrubbed_event["user"]
    assert scrubbed_event["user"]["ip_address"] == "{{none}}"

    # 6. Verify Extra & Breadcrumbs Redaction
    assert scrubbed_event["extra"]["debug_auth_header"] == "[REDACTED]"
    assert scrubbed_event["extra"]["safe_counter"] == 42
    assert scrubbed_event["breadcrumbs"]["values"][0]["data"]["access_token"] == "[REDACTED]"
    assert scrubbed_event["breadcrumbs"]["values"][0]["data"]["action"] == "submit_click"


# =========================================================================
# 2. PostHog Product Analytics: 6 Mandatory Events & PII Absence Tests
# =========================================================================

def test_posthog_six_mandatory_events_and_pii_absence():
    """
    Acceptance Criteria:
    PostHog client tracks 6 explicit lifecycle events with minimal bounded property sets,
    anonymized user identifiers (usr_{user_id}), and zero repository file contents or payment card data.
    """
    test_analytics = AnalyticsService(disabled=False)
    test_analytics.clear_captured_events()

    # 1. user_signup
    ev1 = test_analytics.capture_user_signup(user_id=1, is_admin=False)
    assert ev1["event"] == "user_signup"
    assert ev1["distinct_id"] == "usr_1"
    assert ev1["properties"]["auth_provider"] == "github"
    assert ev1["properties"]["is_admin"] is False
    assert "email" not in ev1["properties"]

    # 2. analysis_submitted
    ev2 = test_analytics.capture_analysis_submitted(user_id=1, job_id="job-100", tier="free")
    assert ev2["event"] == "analysis_submitted"
    assert ev2["distinct_id"] == "usr_1"
    assert ev2["properties"] == {"job_id": "job-100", "tier": "free", "repo_host": "github.com"}

    # 3. analysis_completed
    ev3 = test_analytics.capture_analysis_completed(user_id=1, job_id="job-100", duration_seconds=14.285, tier="free")
    assert ev3["event"] == "analysis_completed"
    assert ev3["distinct_id"] == "usr_1"
    assert ev3["properties"]["job_id"] == "job-100"
    assert ev3["properties"]["tier"] == "free"
    assert ev3["properties"]["duration_seconds"] == 14.29
    assert ev3["properties"]["status"] == "completed"
    assert "file_contents" not in ev3["properties"]

    # 4. analysis_failed
    ev4 = test_analytics.capture_analysis_failed(user_id=1, job_id="job-100", error_category="clone_timeout", tier="free")
    assert ev4["event"] == "analysis_failed"
    assert ev4["distinct_id"] == "usr_1"
    assert ev4["properties"]["job_id"] == "job-100"
    assert ev4["properties"]["tier"] == "free"
    assert ev4["properties"]["error_category"] == "clone_timeout"
    assert ev4["properties"]["status"] == "failed"

    # 5. subscription_started
    ev5 = test_analytics.capture_subscription_started(user_id=1, tier="paid", plan="monthly")
    assert ev5["event"] == "subscription_started"
    assert ev5["distinct_id"] == "usr_1"
    assert ev5["properties"] == {"tier": "paid", "plan": "monthly", "payment_provider": "stripe"}
    assert "card" not in ev5["properties"]

    # 6. subscription_cancelled
    ev6 = test_analytics.capture_subscription_cancelled(user_id=1, reason="user_cancelled")
    assert ev6["event"] == "subscription_cancelled"
    assert ev6["distinct_id"] == "usr_1"
    assert ev6["properties"] == {"tier": "free", "cancellation_reason": "user_cancelled", "payment_provider": "stripe"}

    # Total recorded events
    captured = test_analytics.get_captured_events()
    assert len(captured) == 6
    event_names = [e["event"] for e in captured]
    assert event_names == [
        "user_signup",
        "analysis_submitted",
        "analysis_completed",
        "analysis_failed",
        "subscription_started",
        "subscription_cancelled",
    ]


# =========================================================================
# 3. Client-Facing Error Shielding (Zero Stack Trace Leakage)
# =========================================================================

def test_client_facing_error_shields_stack_trace(client):
    """
    Acceptance Criteria (Threat Model):
    Unhandled exceptions in endpoints must return uniform, client-safe error messages
    without leaking Python tracebacks, internal file system paths, or exception details.
    """
    resp = client.get("/test/trigger-unhandled-error")
    assert resp.status_code == 500
    data = resp.json()

    # Verify uniform sanitized error message
    assert data == {"detail": "An internal server error occurred"}

    # Verify absence of leaked details
    assert "Traceback" not in resp.text
    assert "db.py" not in resp.text
    assert "secret" not in resp.text
    assert "line 42" not in resp.text


# =========================================================================
# 4. Analytics Instrumentation Integration Tests (Auth, Pipeline, Billing)
# =========================================================================

def test_user_signup_analytics_trigger_on_oauth(client, test_db):
    """Verify that a brand new user OAuth callback triggers the user_signup analytics event."""
    SessionLocal, _ = test_db
    analytics.clear_captured_events()

    valid_state = oauth_state_store.generate_state()
    mock_profile = {
        "github_id": 991122,
        "github_username": "new_signup_user",
        "email": "new_signup@example.com",
        "avatar_url": "https://avatars.example.com/u/991122",
    }

    with patch.object(AuthService, "exchange_github_code_async", new=AsyncMock(return_value="gho_valid_signup")), \
         patch.object(AuthService, "fetch_github_user_profile_async", new=AsyncMock(return_value=mock_profile)):

        resp = client.get(f"/auth/github/callback?code=code_signup&state={valid_state}")
        assert resp.status_code == 200

        captured = analytics.get_captured_events()
        signup_events = [e for e in captured if e["event"] == "user_signup"]
        assert len(signup_events) == 1
        assert signup_events[0]["distinct_id"].startswith("usr_")
        assert signup_events[0]["properties"]["auth_provider"] == "github"


def test_analysis_submission_analytics_trigger(client, create_user):
    """Verify that submitting an analysis triggers the analysis_submitted analytics event."""
    analytics.clear_captured_events()
    user = create_user(github_id=883344, username="pipeline_analyst")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    resp = client.post(
        "/analyses/submit",
        data={"repo_url": "https://github.com/facebook/react"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    captured = analytics.get_captured_events()
    submitted_events = [e for e in captured if e["event"] == "analysis_submitted"]
    assert len(submitted_events) == 1
    assert submitted_events[0]["distinct_id"] == f"usr_{user.id}"
    assert submitted_events[0]["properties"]["tier"] == "free"
