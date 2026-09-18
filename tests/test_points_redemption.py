"""Unit, Integration, Concurrency, and Quota Gating Tests for Points Redemption & Badges (Prompt 24)."""

import os
import threading
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user, get_current_user_optional, get_db
from app.core.config import get_settings
from app.db.session import Base, init_db
from app.main import app
from app.models.db import (
    AnalysisJobModel,
    MilestoneAttemptModel,
    PointsLedgerModel,
    SubscriptionModel,
    UserModel,
    utc_now,
)
from app.services.billing_service import BillingService
from app.services.points_engine import PointsEngine, PointsRedemptionError


@pytest.fixture
def test_db_session_factory():
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(target_engine=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    return TestingSessionLocal


@pytest.fixture
def db_session(test_db_session_factory):
    session = test_db_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_users(db_session):
    # Free Tier User
    free_user = db_session.query(UserModel).filter_by(github_id=8801).first()
    if not free_user:
        free_user = UserModel(
            github_id=8801,
            github_username="carol_free",
            email="carol@example.com",
            is_admin=False,
        )
        db_session.add(free_user)

    # Paid Tier User (Pro)
    paid_user = db_session.query(UserModel).filter_by(github_id=8802).first()
    if not paid_user:
        paid_user = UserModel(
            github_id=8802,
            github_username="dave_pro",
            email="dave@example.com",
            is_admin=False,
        )
        db_session.add(paid_user)
        db_session.commit()
        db_session.refresh(paid_user)

        # Attach active Stripe Pro subscription
        sub = SubscriptionModel(
            user_id=paid_user.id,
            stripe_customer_id="cus_test_pro_dave",
            stripe_subscription_id="sub_test_pro_dave",
            status="active",
            current_period_end=utc_now() + timedelta(days=30),
        )
        db_session.add(sub)

    db_session.commit()
    db_session.refresh(free_user)
    db_session.refresh(paid_user)
    return free_user, paid_user


def test_quota_perk_redemption_and_balance_deduction(db_session, test_users):
    """
    Test that redeeming quota perk deducts 100 points via negative ledger entry
    and increases effective monthly quota by +2.
    """
    free_user, _ = test_users

    # Award 150 points to free_user
    entry = PointsLedgerModel(
        user_id=free_user.id,
        job_id=None,
        milestone_tier=1,
        points_awarded=150,
        multiplier_applied=1.0,
        reason="milestone_solved_no_hints",
        created_at=utc_now(),
    )
    db_session.add(entry)
    db_session.commit()

    initial_balance = PointsEngine.get_user_points_balance(db_session, free_user.id)
    assert initial_balance >= 150

    initial_effective_quota = BillingService.get_effective_quota_limit(free_user.id, db_session)
    assert initial_effective_quota == 5  # Base default

    # Redeem Quota Perk (100 PTS -> +2 Quota)
    res = PointsEngine.redeem_quota_perk(db_session, free_user)
    assert res["success"] is True
    assert res["points_spent"] == 100
    assert res["new_balance"] == initial_balance - 100
    assert res["monthly_quota_bonus"] == 2
    assert res["effective_monthly_quota"] == initial_effective_quota + 2

    # Verify negative ledger entry
    ledger_entry = db_session.get(PointsLedgerModel, res["ledger_id"])
    assert ledger_entry is not None
    assert ledger_entry.points_awarded == -100
    assert ledger_entry.reason == "redemption_quota_bump_2"


def test_real_pipeline_quota_gating_unlocked_by_redemption(db_session, test_users):
    """
    Real test: User who hits 5/5 quota limit is blocked from running analyses.
    After redeeming +2 quota, effective limit becomes 7, and subsequent analysis succeeds!
    """
    free_user, _ = test_users

    # Simulate 5 usage events (consuming all base quota)
    from app.storage.billing_repository import BillingRepository
    for _ in range(5):
        BillingRepository.record_usage_event(db_session, free_user.id, "repo_analysis")
    db_session.commit()

    # Reset bonus by clearing prior test redemptions for clean test isolation
    db_session.query(PointsLedgerModel).filter(
        PointsLedgerModel.user_id == free_user.id,
        PointsLedgerModel.reason.startswith("redemption_quota_bump"),
    ).delete()
    db_session.commit()

    # User is currently at 5/5 usage (or higher)
    usage = BillingRepository.get_monthly_usage_count(db_session, free_user.id)
    limit = BillingService.get_effective_quota_limit(free_user.id, db_session)
    assert usage >= limit

    # Attempting to consume quota now fails (HTTP 402 equivalent)
    is_allowed, cur_usage, quota_lim, tier = BillingService.check_and_consume_quota(free_user, db_session)
    assert is_allowed is False
    assert tier == "free"

    # Grant 100 points and redeem +2 quota perk
    credit_entry = PointsLedgerModel(
        user_id=free_user.id,
        job_id=None,
        milestone_tier=1,
        points_awarded=100,
        multiplier_applied=1.0,
        reason="bonus_credit",
        created_at=utc_now(),
    )
    db_session.add(credit_entry)
    db_session.commit()

    # Execute redemption
    PointsEngine.redeem_quota_perk(db_session, free_user)

    # Effective quota is now expanded
    new_limit = BillingService.get_effective_quota_limit(free_user.id, db_session)
    assert new_limit == limit + 2

    # Gating check now passes!
    is_allowed_after, cur_u_after, q_lim_after, tier_after = BillingService.check_and_consume_quota(free_user, db_session)
    assert is_allowed_after is True
    assert q_lim_after == new_limit


def test_paid_pro_tier_redemption_rejection(db_session, test_users):
    """Paid/Pro users have unlimited analyses; redeeming extra quota is rejected with HTTP 400."""
    _, paid_user = test_users

    # Award points to paid user
    db_session.add(PointsLedgerModel(
        user_id=paid_user.id,
        job_id=None,
        milestone_tier=1,
        points_awarded=200,
        multiplier_applied=1.0,
        reason="test_grant",
        created_at=utc_now(),
    ))
    db_session.commit()

    initial_balance = PointsEngine.get_user_points_balance(db_session, paid_user.id)

    with pytest.raises(PointsRedemptionError) as exc_info:
        PointsEngine.redeem_quota_perk(db_session, paid_user)

    assert "already on Backtrace Pro with unlimited repository analyses" in str(exc_info.value)
    assert exc_info.value.status_code == 400

    # Ensure zero points deducted
    assert PointsEngine.get_user_points_balance(db_session, paid_user.id) == initial_balance


def test_insufficient_balance_rejection(db_session, test_users):
    """User with insufficient balance cannot redeem perk."""
    # Create fresh user with 0 points
    poor_user = UserModel(
        github_id=8803,
        github_username="eve_broke",
        email="eve@example.com",
    )
    db_session.add(poor_user)
    db_session.commit()
    db_session.refresh(poor_user)

    # Award 50 points (less than required 100)
    db_session.add(PointsLedgerModel(
        user_id=poor_user.id,
        job_id=None,
        milestone_tier=1,
        points_awarded=50,
        multiplier_applied=1.0,
        reason="milestone_1",
        created_at=utc_now(),
    ))
    db_session.commit()

    with pytest.raises(PointsRedemptionError) as exc_info:
        PointsEngine.redeem_quota_perk(db_session, poor_user)

    assert "Insufficient point balance" in str(exc_info.value)
    assert exc_info.value.status_code == 400


def test_concurrency_anti_double_spend(test_db_session_factory):
    """
    Two near-simultaneous redemption requests with a balance of 100 points:
    Exactly one succeeds and the other is rejected with Insufficient point balance.
    """
    session = test_db_session_factory()
    racer = UserModel(github_id=8804, github_username="racer_user", email="racer@example.com")
    session.add(racer)
    session.commit()
    session.refresh(racer)

    # Fund with exactly 100 points (can only afford ONE perk)
    session.add(PointsLedgerModel(
        user_id=racer.id,
        job_id=None,
        milestone_tier=1,
        points_awarded=100,
        multiplier_applied=1.0,
        reason="exact_100_grant",
        created_at=utc_now(),
    ))
    session.commit()

    user_id_val = racer.id
    successes = []
    failures = []

    def redemption_worker():
        w_sess = test_db_session_factory()
        try:
            w_user = w_sess.get(UserModel, user_id_val)
            res = PointsEngine.redeem_quota_perk(w_sess, w_user)
            successes.append(res)
        except PointsRedemptionError as exc:
            failures.append(exc)
        finally:
            w_sess.close()

    t1 = threading.Thread(target=redemption_worker)
    t2 = threading.Thread(target=redemption_worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one succeeded and one failed
    assert len(successes) == 1
    assert len(failures) == 1
    assert "Insufficient point balance" in failures[0].message

    # Balance is now exactly 0
    final_balance = PointsEngine.get_user_points_balance(session, user_id_val)
    assert final_balance == 0

    session.close()


def test_badges_unlock_criteria(db_session):
    """Verify the 5 badges unlock based on real database conditions."""
    badge_user = UserModel(github_id=8805, github_username="badge_master", email="badges@example.com")
    db_session.add(badge_user)
    db_session.commit()
    db_session.refresh(badge_user)

    # 1. Initial State: All badges locked
    badges_init = PointsEngine.get_user_badges(db_session, badge_user.id)
    assert len(badges_init) == 5
    assert all(not b["earned"] for b in badges_init)

    # 2. Solve 1 Milestone -> "First Milestone" unlocks
    job1 = AnalysisJobModel(user_id=badge_user.id, repo_name="repo1", github_url="https://github.com/org/repo1", run_id="r1")
    db_session.add(job1)
    db_session.commit()

    db_session.add(MilestoneAttemptModel(
        user_id=badge_user.id, job_id=job1.id, milestone_tier=1,
        submitted_code="pass", status="structurally_verified",
        hint_level_revealed=0, implementation_revealed=False
    ))
    db_session.commit()

    badges_step1 = PointsEngine.get_user_badges(db_session, badge_user.id)
    first_m = next(b for b in badges_step1 if b["id"] == "first_milestone")
    assert first_m["earned"] is True

    # 3. Add 4 more zero-hint solves on other milestones (Total 5 zero-hint solves)
    for tier_i in range(2, 6):
        db_session.add(MilestoneAttemptModel(
            user_id=badge_user.id, job_id=job1.id, milestone_tier=tier_i,
            submitted_code="pass", status="structurally_verified",
            hint_level_revealed=0, implementation_revealed=False
        ))
    db_session.commit()

    badges_step2 = PointsEngine.get_user_badges(db_session, badge_user.id)
    zero_hint_badge = next(b for b in badges_step2 if b["id"] == "zero_hint_streak_5")
    assert zero_hint_badge["earned"] is True

    # 4. Solves on 2 more distinct repos (Total 3 repos) -> "Repo Explorer" unlocks
    job2 = AnalysisJobModel(user_id=badge_user.id, repo_name="repo2", github_url="https://github.com/org/repo2", run_id="r2")
    job3 = AnalysisJobModel(user_id=badge_user.id, repo_name="repo3", github_url="https://github.com/org/repo3", run_id="r3")
    db_session.add_all([job2, job3])
    db_session.commit()

    db_session.add(MilestoneAttemptModel(user_id=badge_user.id, job_id=job2.id, milestone_tier=1, status="structurally_verified"))
    db_session.add(MilestoneAttemptModel(user_id=badge_user.id, job_id=job3.id, milestone_tier=1, status="structurally_verified"))
    db_session.commit()

    badges_step3 = PointsEngine.get_user_badges(db_session, badge_user.id)
    explorer_badge = next(b for b in badges_step3 if b["id"] == "repo_explorer")
    assert explorer_badge["earned"] is True

    # 5. Earn 100 lifetime points -> "Century Club" unlocks
    db_session.add(PointsLedgerModel(
        user_id=badge_user.id, job_id=job1.id, milestone_tier=1,
        points_awarded=100, multiplier_applied=1.0, reason="milestone_solved_no_hints"
    ))
    db_session.commit()

    badges_step4 = PointsEngine.get_user_badges(db_session, badge_user.id)
    century_badge = next(b for b in badges_step4 if b["id"] == "century_club")
    assert century_badge["earned"] is True


def test_leaderboard_and_sticky_user_rank(db_session):
    """Verify leaderboard ranks users and pins current user rank accurately."""
    u1 = UserModel(github_id=9901, github_username="alpha_top", email="alpha@example.com")
    u2 = UserModel(github_id=9902, github_username="beta_mid", email="beta@example.com")
    u3 = UserModel(github_id=9903, github_username="gamma_low", email="gamma@example.com")
    db_session.add_all([u1, u2, u3])
    db_session.commit()

    # Award points: u1=5000, u2=3000, u3=1000 to isolate rank from other test fixtures
    db_session.add(PointsLedgerModel(user_id=u1.id, points_awarded=5000, multiplier_applied=1.0, reason="test", job_id=None, milestone_tier=1))
    db_session.add(PointsLedgerModel(user_id=u2.id, points_awarded=3000, multiplier_applied=1.0, reason="test", job_id=None, milestone_tier=1))
    db_session.add(PointsLedgerModel(user_id=u3.id, points_awarded=1000, multiplier_applied=1.0, reason="test", job_id=None, milestone_tier=1))
    db_session.commit()

    lb_for_u2 = PointsEngine.get_leaderboard(db_session, current_user_id=u2.id, limit=2)
    assert lb_for_u2["current_user_rank"] == 2
    assert lb_for_u2["current_user_points"] >= 3000
    assert lb_for_u2["leaderboard"][0]["username"] == "alpha_top"
    assert lb_for_u2["leaderboard"][1]["username"] == "beta_mid"


def test_rewards_frontend_pages_and_actions(db_session, test_users):
    """Test GET /rewards page render and POST /rewards/redeem/quota form action."""
    free_user, _ = test_users

    # Fund user with 150 points
    db_session.add(PointsLedgerModel(
        user_id=free_user.id,
        job_id=None,
        milestone_tier=1,
        points_awarded=150,
        multiplier_applied=1.0,
        reason="milestone_solved_no_hints",
        created_at=utc_now(),
    ))
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user_optional] = lambda: free_user
    app.dependency_overrides[get_current_user] = lambda: free_user

    client = TestClient(app)

    try:
        # 1. GET /rewards renders successfully
        resp_page = client.get("/rewards")
        assert resp_page.status_code == 200
        assert "Points & Rewards Protocol" in resp_page.text
        assert "Dossier Prestige Badges" in resp_page.text
        assert "Global Builder Leaderboard" in resp_page.text
        assert "Points Audit Ledger" in resp_page.text
        assert "Redeem +2 Repos (100 PTS)" in resp_page.text

        # 2. Form action POST /rewards/redeem/quota succeeds and redirects with flash message
        resp_post = client.post("/rewards/redeem/quota", follow_redirects=False)
        assert resp_post.status_code == 302
        assert "/rewards?success=" in resp_post.headers["location"]

    finally:
        app.dependency_overrides.clear()
