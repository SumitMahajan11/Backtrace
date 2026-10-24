"""Test Suite for Settings Clean-up, Rewards Feature Flag, Export, Deletion, Footer, and Cookie Security."""

import json
import os
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.core.config import get_settings
from app.db.session import Base
from app.main import app
from app.models.db import (
    AnalysisJobModel,
    MilestoneAttemptModel,
    PointsLedgerModel,
    RefreshTokenModel,
    SubscriptionModel,
    UsageEventModel,
    UserModel,
    utc_now,
)
from app.security.auth import create_access_token
from app.services.points_engine import PointsEngine
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

    def _create(github_id: int, username: str, email: str = None, show_on_leaderboard: bool = False) -> UserModel:
        with SessionLocal() as session:
            user = UserRepository.upsert_github_user(
                session=session,
                github_id=github_id,
                github_username=username,
                email=email or f"{username}@example.com",
                avatar_url=f"https://avatars.example.com/{username}",
            )
            user.show_on_leaderboard = show_on_leaderboard
            session.commit()
            session.refresh(user)
            return user

    return _create


# =========================================================================
# 1. Rewards Flag: Enabled vs Disabled (Nav Link & 404 Route)
# =========================================================================

def test_rewards_disabled_by_default(client, create_user):
    """When REWARDS_ENABLED is false (default), nav link is absent and routes return 404."""
    user = create_user(github_id=101, username="test_user_rewards_off")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with patch.dict(os.environ, {"REWARDS_ENABLED": "false"}):
        # 1. Dashboard navigation has no link to /rewards
        resp_dash = client.get("/dashboard")
        assert resp_dash.status_code == 200
        assert 'href="/rewards"' not in resp_dash.text
        assert 'id="nav-link-rewards"' not in resp_dash.text

        # 2. Direct route access to /rewards returns 404
        resp_rewards = client.get("/rewards")
        assert resp_rewards.status_code == 404

        # 3. /points alias returns 404
        resp_points = client.get("/points")
        assert resp_points.status_code == 404

        # 4. Quota redemption form action returns 404
        resp_redeem = client.post("/rewards/redeem/quota")
        assert resp_redeem.status_code == 404


def test_rewards_enabled_state(client, create_user):
    """When REWARDS_ENABLED is 'true', nav link is present and /rewards returns 200."""
    user = create_user(github_id=102, username="test_user_rewards_on")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with patch.dict(os.environ, {"REWARDS_ENABLED": "true"}):
        # 1. Dashboard nav contains Rewards & Badges link
        resp_dash = client.get("/dashboard")
        assert resp_dash.status_code == 200
        assert 'href="/rewards"' in resp_dash.text

        # 2. Direct route access to /rewards returns 200
        resp_rewards = client.get("/rewards")
        assert resp_rewards.status_code == 200
        assert "Rewards" in resp_rewards.text or "Points" in resp_rewards.text


# =========================================================================
# 2. Leaderboard Username Privacy & Settings Checkbox
# =========================================================================

def test_leaderboard_username_masking(test_db, create_user):
    """Leaderboard shows GitHub username only if show_on_leaderboard=True; otherwise 'Anonymous'."""
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        u_public = create_user(github_id=201, username="public_hero", show_on_leaderboard=True)
        u_private = create_user(github_id=202, username="secret_coder", show_on_leaderboard=False)

        # Award points to both users via PointsLedgerModel
        pl1 = PointsLedgerModel(
            user_id=u_public.id,
            points_awarded=100,
            multiplier_applied=1.0,
            reason="milestone_solved_no_hints",
        )
        pl2 = PointsLedgerModel(
            user_id=u_private.id,
            points_awarded=90,
            multiplier_applied=1.0,
            reason="milestone_solved_no_hints",
        )
        session.add(pl1)
        session.add(pl2)
        session.commit()

        leaderboard_data = PointsEngine.get_leaderboard(session, current_user_id=u_public.id, limit=10)
        entries = leaderboard_data["leaderboard"]

        usernames = [entry["username"] for entry in entries]
        # public_hero should be visible with username
        assert "public_hero" in usernames
        # secret_coder must NOT be in usernames; must be "Anonymous"
        assert "secret_coder" not in usernames
        assert "Anonymous" in usernames


def test_settings_leaderboard_checkbox_and_toggle(client, create_user, test_db):
    """Settings page renders checkbox and POST /settings updates show_on_leaderboard boolean."""
    user = create_user(github_id=203, username="checkbox_user", show_on_leaderboard=False)
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    # 1. GET /settings shows the checkbox unchecked
    resp_get = client.get("/settings")
    assert resp_get.status_code == 200
    assert 'name="show_on_leaderboard"' in resp_get.text
    assert "Show my username on the leaderboard" in resp_get.text

    # 2. POST /settings with show_on_leaderboard=true
    resp_post = client.post("/settings", data={"show_on_leaderboard": "true"}, follow_redirects=False)
    assert resp_post.status_code == 302
    assert "Preferences+updated" in resp_post.headers["location"]

    SessionLocal, _ = test_db
    with SessionLocal() as session:
        db_user = session.get(UserModel, user.id)
        assert db_user.show_on_leaderboard is True

    # 3. POST /settings without show_on_leaderboard unchecks it
    resp_post2 = client.post("/settings", data={}, follow_redirects=False)
    assert resp_post2.status_code == 302
    with SessionLocal() as session:
        db_user = session.get(UserModel, user.id)
        assert db_user.show_on_leaderboard is False


# =========================================================================
# 3. Settings Identity Row: Single Row, Check Icon, Connected Date in <time>
# =========================================================================

def test_settings_identity_single_row_and_time_tag(client, create_user):
    """Settings displays 'GitHub connected' once with check icon, username, and local <time> tag."""
    user = create_user(github_id=301, username="octocat_pro")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.text

    # Single "GitHub connected" text
    assert html.count("GitHub connected:") == 1
    assert "@octocat_pro" in html

    # Duplicate badge and tag removed
    assert "GITHUB OAUTH CONNECTED" not in html
    assert '<span class="badge badge-completed">CONNECTED</span>' not in html

    # <time> element present for connected date
    assert "<time datetime=" in html
    assert "Connected: <time" in html


# =========================================================================
# 4. Export My Data (GET /account/export.json)
# =========================================================================

def test_export_account_data(client, create_user, test_db):
    """GET /account/export.json returns JSON file with user's jobs, progress, and quiz scores."""
    user = create_user(github_id=401, username="export_user")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    SessionLocal, _ = test_db
    with SessionLocal() as session:
        # Create an analysis job
        job = AnalysisJobModel(
            user_id=user.id,
            repo_name="sample-repo",
            github_url="https://github.com/example/sample-repo",
            run_id="run-exp-001",
            status="complete",
            execution_time_seconds=12.5,
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        # Create milestone attempt with quiz scores in grading_details_json
        details = {
            "quiz_score": 3,
            "quiz_total": 4,
            "quiz_passed": True,
            "quiz_recorded_at": utc_now().isoformat(),
        }
        attempt = MilestoneAttemptModel(
            user_id=user.id,
            job_id=job.id,
            milestone_tier=1,
            status="structurally_verified",
            grading_method="quiz_and_structural",
            grading_details_json=json.dumps(details),
        )
        session.add(attempt)
        session.commit()

    resp = client.get("/account/export.json")
    assert resp.status_code == 200
    assert "attachment; filename=\"backtrace_export_export_user.json\"" in resp.headers.get("content-disposition", "")

    data = resp.json()
    assert data["user"]["github_username"] == "export_user"
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["repo_name"] == "sample-repo"
    assert len(data["progress"]) == 1
    assert data["progress"][0]["milestone_tier"] == 1
    assert len(data["quiz_scores"]) == 1
    assert data["quiz_scores"][0]["quiz_score"] == 3
    assert data["quiz_scores"][0]["quiz_total"] == 4


def test_export_unauthenticated_redirect(client):
    """Unauthenticated GET /account/export.json redirects to /login."""
    resp = client.get("/account/export.json", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


# =========================================================================
# 5. Delete My Account (POST /account/delete)
# =========================================================================

def test_delete_account_username_validation(client, create_user):
    """POST /account/delete fails with 400 if confirmation username does not match."""
    user = create_user(github_id=501, username="delete_target")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    # Wrong username
    resp = client.post("/account/delete", data={"username": "wrong_username"})
    assert resp.status_code == 400
    assert "does not match account username" in resp.text


def test_delete_account_cascades_all_referenced_tables(client, create_user, test_db):
    """
    POST /account/delete successfully removes the user and their rows from ALL 6 tables
    referencing user_id:
    1. analysis_jobs
    2. milestone_attempts
    3. points_ledger
    4. refresh_tokens
    5. subscriptions
    6. usage_events
    plus the users table.
    """
    user = create_user(github_id=502, username="to_be_purged")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    SessionLocal, _ = test_db
    with SessionLocal() as session:
        # 1. analysis_jobs
        job = AnalysisJobModel(
            user_id=user.id,
            repo_name="purge-repo",
            github_url="https://github.com/purge/repo",
            run_id="run-purge-001",
            status="complete",
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        # 2. milestone_attempts
        attempt = MilestoneAttemptModel(
            user_id=user.id,
            job_id=job.id,
            milestone_tier=1,
            status="attempting",
        )
        session.add(attempt)

        # 3. points_ledger
        pl = PointsLedgerModel(
            user_id=user.id,
            job_id=job.id,
            milestone_tier=1,
            points_awarded=50,
            reason="milestone_solved_no_hints",
        )
        session.add(pl)

        # 4. refresh_tokens
        rt = RefreshTokenModel(
            user_id=user.id,
            token_hash="fakehash1234567890abcdef",
            expires_at=utc_now(),
        )
        session.add(rt)

        # 5. subscriptions
        sub = SubscriptionModel(
            user_id=user.id,
            stripe_customer_id="cus_test123",
            status="active",
        )
        session.add(sub)

        # 6. usage_events
        ue = UsageEventModel(
            user_id=user.id,
            event_type="repo_analysis",
        )
        session.add(ue)
        session.commit()

        # Sanity check: confirm 1 row exists in each table for this user_id
        user_id = user.id
        assert session.query(AnalysisJobModel).filter(AnalysisJobModel.user_id == user_id).count() == 1
        assert session.query(MilestoneAttemptModel).filter(MilestoneAttemptModel.user_id == user_id).count() == 1
        assert session.query(PointsLedgerModel).filter(PointsLedgerModel.user_id == user_id).count() == 1
        assert session.query(RefreshTokenModel).filter(RefreshTokenModel.user_id == user_id).count() == 1
        assert session.query(SubscriptionModel).filter(SubscriptionModel.user_id == user_id).count() == 1
        assert session.query(UsageEventModel).filter(UsageEventModel.user_id == user_id).count() == 1
        assert session.query(UserModel).filter(UserModel.id == user_id).count() == 1

    # Execute deletion
    resp = client.post("/account/delete", data={"username": "to_be_purged"}, follow_redirects=False)
    assert resp.status_code == 302
    assert "/login?deleted=1" in resp.headers["location"]

    # Verify cookies cleared
    set_cookies = resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else [resp.headers.get("set-cookie", "")]
    set_cookie_str = " ".join(set_cookies)
    assert 'access_token=""' in set_cookie_str or "access_token=;" in set_cookie_str or "Max-Age=0" in set_cookie_str

    # Verify all 6 dependent tables + users have 0 rows for user_id
    with SessionLocal() as session:
        assert session.query(AnalysisJobModel).filter(AnalysisJobModel.user_id == user_id).count() == 0
        assert session.query(MilestoneAttemptModel).filter(MilestoneAttemptModel.user_id == user_id).count() == 0
        assert session.query(PointsLedgerModel).filter(PointsLedgerModel.user_id == user_id).count() == 0
        assert session.query(RefreshTokenModel).filter(RefreshTokenModel.user_id == user_id).count() == 0
        assert session.query(SubscriptionModel).filter(SubscriptionModel.user_id == user_id).count() == 0
        assert session.query(UsageEventModel).filter(UsageEventModel.user_id == user_id).count() == 0
        assert session.query(UserModel).filter(UserModel.id == user_id).count() == 0


# =========================================================================
# 6. Footer Links: Privacy, Pricing, Support Targets & Billing Toggle
# =========================================================================

def test_static_pages_exist(client):
    """GET /privacy, /pricing, and /support all return 200 with required content."""
    # 1. /privacy
    resp_priv = client.get("/privacy")
    assert resp_priv.status_code == 200
    assert "What data is stored" in resp_priv.text
    assert "GitHub username" in resp_priv.text
    assert "Analysis results" in resp_priv.text
    assert "Delete my account" in resp_priv.text
    assert "support@backtrace.dev" in resp_priv.text

    # 2. /support
    resp_sup = client.get("/support")
    assert resp_sup.status_code == 200
    assert "Support &amp; Assistance" in resp_sup.text
    assert "support@backtrace.dev" in resp_sup.text

    # 3. /pricing
    resp_price = client.get("/pricing")
    assert resp_price.status_code == 200
    assert "Pricing" in resp_price.text


def test_footer_pricing_visibility_with_billing_flag(client):
    """Footer hides Pricing link when STRIPE_BILLING_ENABLED is false; shows when true."""
    # When billing is disabled
    with patch.dict(os.environ, {"STRIPE_BILLING_ENABLED": "false"}):
        resp = client.get("/privacy")
        assert resp.status_code == 200
        # Privacy and Support exist
        assert 'href="/privacy"' in resp.text
        assert 'href="/support"' in resp.text
        # Pricing link should be hidden
        assert 'href="/pricing"' not in resp.text

    # When billing is enabled
    with patch.dict(os.environ, {"STRIPE_BILLING_ENABLED": "true"}):
        resp2 = client.get("/privacy")
        assert resp2.status_code == 200
        assert 'href="/privacy"' in resp2.text
        assert 'href="/pricing"' in resp2.text
        assert 'href="/support"' in resp2.text


# =========================================================================
# 7. Session Cookie HTTPS Security: Secure, HttpOnly, SameSite=Lax
# =========================================================================

def test_session_cookies_secure_behind_https(client, create_user, test_db):
    """Session cookies have Secure, HttpOnly, and SameSite=Lax when running behind HTTPS."""
    from app.services.auth_service import AuthService
    user = create_user(github_id=701, username="https_user")
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        tokens = AuthService.issue_token_pair(session, user)
        session.commit()

    resp = client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert resp.status_code == 200
    cookies = resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else [resp.headers.get("set-cookie", "")]
    cookie_str = " ".join(cookies)
    # Confirm flags
    assert "httponly" in cookie_str.lower()
    assert "samesite=lax" in cookie_str.lower()
    assert "secure" in cookie_str.lower()


def test_session_cookies_not_secure_on_plain_http(client, create_user, test_db):
    """Session cookies do not enforce Secure when running on plain HTTP in dev environment."""
    from app.services.auth_service import AuthService
    user = create_user(github_id=702, username="http_user")
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        tokens = AuthService.issue_token_pair(session, user)
        session.commit()

    with patch.dict(os.environ, {"ENVIRONMENT": "development"}):
        resp = client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
            headers={"X-Forwarded-Proto": "http"},
        )
        assert resp.status_code == 200
        cookies = resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else [resp.headers.get("set-cookie", "")]
        cookie_str = " ".join(cookies)
        assert "httponly" in cookie_str.lower()
        assert "samesite=lax" in cookie_str.lower()
        assert "secure" not in cookie_str.lower()


def test_is_secure_cookie_headers():
    """Directly verifies _is_secure_cookie logic for forwarded headers and schemes."""
    from app.api.auth import _is_secure_cookie
    from starlette.requests import Request

    # HTTPS via X-Forwarded-Proto
    r1 = Request({"type": "http", "path": "/", "headers": [(b"x-forwarded-proto", b"https")], "scheme": "http"})
    assert _is_secure_cookie(r1) is True

    # HTTPS via URL scheme
    r2 = Request({"type": "http", "path": "/", "headers": [], "scheme": "https"})
    assert _is_secure_cookie(r2) is True

    # HTTPS via X-Forwarded-Ssl
    r3 = Request({"type": "http", "path": "/", "headers": [(b"x-forwarded-ssl", b"on")], "scheme": "http"})
    assert _is_secure_cookie(r3) is True

    # Plain HTTP in development
    with patch.dict(os.environ, {"ENVIRONMENT": "development"}):
        r4 = Request({"type": "http", "path": "/", "headers": [(b"x-forwarded-proto", b"http")], "scheme": "http"})
        assert _is_secure_cookie(r4) is False


def test_xss_prevention_in_settings_and_export(client, create_user):
    """XSS injection payloads in query params or inputs are safely escaped in Settings view."""
    xss_payload = '<script>alert("xss")</script><img src=x onerror=alert(1)>'
    user = create_user(github_id=9999, username="xss_hacker")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    # Query param XSS in Settings view
    resp = client.get(f"/settings?error={xss_payload}&success={xss_payload}")
    assert resp.status_code == 200
    assert '<script>alert("xss")</script>' not in resp.text
    assert '<img src=x onerror=alert(1)>' not in resp.text

    # Export download contains expected data safely encoded
    resp_exp = client.get("/account/export.json")
    assert resp_exp.status_code == 200
    assert resp_exp.headers.get("content-type") == "application/json"
    data = resp_exp.json()
    assert data["user"]["github_username"] == "xss_hacker"
