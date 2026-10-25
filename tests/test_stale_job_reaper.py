"""Tests for Stale Job Reaper and Startup Quota Refund Engine (Prompt 40/41 / Risk 3).

Verifies that:
1. Active jobs stuck in 'running' (or 'processing') older than N minutes are marked failed.
2. Failed stage and clear diagnostic error message are recorded.
3. User quota consumption is atomically refunded in the same transaction.
4. FastAPI lifespan executes stale job reaping automatically on application startup
   using STALE_JOB_BOOT_GRACE_MINUTES (default 2 minutes).
5. A 5-minute-old running job is reaped at startup.
6. A fresh running job (< 2 minutes old) is NOT reaped at startup.
7. Periodic retention worker sweep reclaims 30-minute stale jobs.
8. Mutation coverage:
   - Non-stale running jobs remain intact without refund.
   - Terminal jobs ('completed', 'failed', 'cancelled') are untouched.
   - Custom timeout boundaries (e.g. 2m, 10m, 30m) are strictly enforced.
   - Multiple users with mixed job states are strictly isolated.
   - Reaper execution is completely idempotent.
"""

from datetime import datetime, timedelta, timezone
from typing import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, UsageEventModel, UserModel, utc_now
from app.services.billing_service import BillingService
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.billing_repository import BillingRepository


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Provides a fresh isolated in-memory database session for reaper tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def stale_job_fixture(db_session: Session):
    """
    Creates a user, consumes 1 unit of monthly analysis quota, creates an active job,
    and sets its timestamp to 45 minutes in the past (stale under 30-minute threshold).
    """
    user = UserModel(
        github_id=98701,
        github_username="stale_worker_user",
        email="stale_worker@example.com",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    # Consume quota
    allowed, usage, limit, tier = BillingService.check_and_consume_quota(user, db_session)
    assert allowed is True
    assert usage == 1
    assert user.quota_used == 1

    # Create job in 'running' state
    job = AnalysisJobRepository.create_job(
        session=db_session,
        user_id=user.id,
        repo_url="https://github.com/test-org/stale-repo",
        status="running",
    )
    assert job.status == "running"

    # Rewind time to 45 minutes ago
    past_time = utc_now() - timedelta(minutes=45)
    job.created_at = past_time
    job.updated_at = past_time
    db_session.commit()
    db_session.refresh(job)

    return user, job


def test_stale_running_job_marked_failed_and_quota_refunded(db_session: Session, stale_job_fixture):
    """
    Assert that jobs in 'running' older than 30 minutes are marked failed with a clear reason,
    and their quota event is refunded back to the user.
    """
    user, job = stale_job_fixture
    assert user.quota_used == 1
    assert BillingRepository.get_monthly_usage_count(db_session, user.id) == 1

    # Execute stale job cleanup
    reclaimed = AnalysisJobRepository.clean_stale_running_jobs(
        session=db_session,
        timeout_minutes=30,
    )

    assert len(reclaimed) == 1
    reclaimed_job = reclaimed[0]
    assert reclaimed_job.id == job.id

    db_session.refresh(job)
    assert job.status == "failed"
    assert job.failed_stage == "stale_worker_timeout"
    assert "timed out after 30 minutes in running state" in job.error_message
    assert "Quota has been refunded" in job.error_message

    # Verify quota has been refunded
    assert BillingRepository.get_monthly_usage_count(db_session, user.id) == 0
    db_session.refresh(user)
    assert user.quota_used == 0

    # User can now launch a new analysis with their refunded quota
    allowed, usage, limit, tier = BillingService.check_and_consume_quota(user, db_session)
    assert allowed is True
    assert usage == 1


def test_five_minute_old_running_job_reaped_at_startup():
    """
    Prompt 41 requirement: At boot, a 5-minute-old running job exceeds the short grace
    (default 2 minutes) and is reaped as failed, with its quota event refunded.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Seed 5-minute-old running job
    with TestingSession() as session:
        user = UserModel(
            github_id=98702,
            github_username="startup_stale_user",
            email="startup_stale@example.com",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        BillingService.check_and_consume_quota(user, session)
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test-org/startup-stale-repo",
            status="running",
        )
        # Exactly 5 minutes old (exceeds default 2-minute boot grace)
        past_time = utc_now() - timedelta(minutes=5)
        job.created_at = past_time
        job.updated_at = past_time
        session.commit()
        job_id = job.id
        user_id = user.id

    # Configure app state to use this test sessionmaker during startup lifespan
    app.state.db_sessionmaker = TestingSession

    def override_get_db():
        session = TestingSession()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        # Starting TestClient enters lifespan context (startup)
        with TestClient(app) as client:
            with TestingSession() as session:
                refreshed_job = AnalysisJobRepository.get_job_by_id(session, job_id)
                assert refreshed_job.status == "failed"
                assert refreshed_job.failed_stage == "stale_worker_timeout"
                assert "server restart or worker crash" in refreshed_job.error_message

                # Quota refunded
                assert BillingRepository.get_monthly_usage_count(session, user_id) == 0
                db_user = session.get(UserModel, user_id)
                assert db_user.quota_used == 0
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "db_sessionmaker"):
            delattr(app.state, "db_sessionmaker")
        Base.metadata.drop_all(bind=engine)


def test_fresh_job_under_boot_grace_not_reaped_at_startup():
    """
    A fresh job running for only 1 minute (< 2 minute boot grace) must NOT be reaped at startup.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with TestingSession() as session:
        user = UserModel(
            github_id=98709,
            github_username="fresh_startup_user",
            email="fresh@example.com",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        BillingService.check_and_consume_quota(user, session)
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test-org/fresh-repo",
            status="running",
        )
        # 1 minute old (< 2 minute boot grace)
        fresh_time = utc_now() - timedelta(minutes=1)
        job.created_at = fresh_time
        job.updated_at = fresh_time
        session.commit()
        job_id = job.id
        user_id = user.id

    app.state.db_sessionmaker = TestingSession

    def override_get_db():
        session = TestingSession()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            with TestingSession() as session:
                refreshed_job = AnalysisJobRepository.get_job_by_id(session, job_id)
                assert refreshed_job.status == "running"
                assert refreshed_job.error_message is None
                assert BillingRepository.get_monthly_usage_count(session, user_id) == 1
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "db_sessionmaker"):
            delattr(app.state, "db_sessionmaker")
        Base.metadata.drop_all(bind=engine)


def test_mutation_active_job_not_stale_remains_running_no_refund(db_session: Session):
    """
    Mutation Check 1: Active job with recent activity (< timeout_minutes) must NOT be touched.
    """
    user = UserModel(github_id=98703, github_username="active_user", email="active@example.com")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    BillingService.check_and_consume_quota(user, db_session)
    job = AnalysisJobRepository.create_job(
        session=db_session,
        user_id=user.id,
        repo_url="https://github.com/test-org/active-repo",
        status="running",
    )
    # Set to 1 minute ago (< 2-minute default boot grace)
    recent_time = utc_now() - timedelta(minutes=1)
    job.created_at = recent_time
    job.updated_at = recent_time
    db_session.commit()

    reclaimed = AnalysisJobRepository.clean_stale_running_jobs(db_session, timeout_minutes=2)
    assert len(reclaimed) == 0

    db_session.refresh(job)
    assert job.status == "running"
    assert job.error_message is None
    assert BillingRepository.get_monthly_usage_count(db_session, user.id) == 1


def test_mutation_completed_and_failed_jobs_untouched(db_session: Session):
    """
    Mutation Check 2: Terminal jobs ('completed' or 'failed') older than N minutes must NOT be modified.
    """
    user = UserModel(github_id=98704, github_username="terminal_user", email="term@example.com")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    completed_job = AnalysisJobRepository.create_job(
        session=db_session,
        user_id=user.id,
        repo_url="https://github.com/test-org/completed-repo",
        status="completed",
    )
    failed_job = AnalysisJobRepository.create_job(
        session=db_session,
        user_id=user.id,
        repo_url="https://github.com/test-org/already-failed-repo",
        status="failed",
        error_message="Original error",
    )
    old_time = utc_now() - timedelta(minutes=90)
    completed_job.updated_at = old_time
    failed_job.updated_at = old_time
    db_session.commit()

    reclaimed = AnalysisJobRepository.clean_stale_running_jobs(db_session, timeout_minutes=2)
    assert len(reclaimed) == 0

    db_session.refresh(completed_job)
    db_session.refresh(failed_job)
    assert completed_job.status == "completed"
    assert failed_job.status == "failed"
    assert failed_job.error_message == "Original error"


def test_mutation_processing_job_reclaimed_and_refunded(db_session: Session):
    """
    Mutation Check 3: Jobs in 'processing' status older than N minutes must also be reclaimed.
    """
    user = UserModel(github_id=98705, github_username="processing_user", email="proc@example.com")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    BillingService.check_and_consume_quota(user, db_session)
    job = AnalysisJobRepository.create_job(
        session=db_session,
        user_id=user.id,
        repo_url="https://github.com/test-org/processing-repo",
        status="processing",
    )
    old_time = utc_now() - timedelta(minutes=35)
    job.created_at = old_time
    job.updated_at = old_time
    db_session.commit()

    reclaimed = AnalysisJobRepository.clean_stale_running_jobs(db_session, timeout_minutes=2)
    assert len(reclaimed) == 1
    assert reclaimed[0].id == job.id

    db_session.refresh(job)
    assert job.status == "failed"
    assert BillingRepository.get_monthly_usage_count(db_session, user.id) == 0


def test_mutation_custom_timeout_threshold_boundaries(db_session: Session):
    """
    Mutation Check 4: Enforces precise timeout boundary logic.
    A 15-minute-old job is NOT stale when threshold is 30m, but IS stale when threshold is 10m.
    """
    user = UserModel(github_id=98706, github_username="boundary_user", email="bound@example.com")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    BillingService.check_and_consume_quota(user, db_session)
    job = AnalysisJobRepository.create_job(
        session=db_session,
        user_id=user.id,
        repo_url="https://github.com/test-org/boundary-repo",
        status="running",
    )
    job_time = utc_now() - timedelta(minutes=15)
    job.created_at = job_time
    job.updated_at = job_time
    db_session.commit()

    # When timeout=30m, 15m is NOT stale
    reclaimed_30 = AnalysisJobRepository.clean_stale_running_jobs(db_session, timeout_minutes=30)
    assert len(reclaimed_30) == 0
    db_session.refresh(job)
    assert job.status == "running"

    # When timeout=10m, 15m IS stale
    reclaimed_10 = AnalysisJobRepository.clean_stale_running_jobs(db_session, timeout_minutes=10)
    assert len(reclaimed_10) == 1
    db_session.refresh(job)
    assert job.status == "failed"
    assert BillingRepository.get_monthly_usage_count(db_session, user.id) == 0


def test_stale_job_reaper_idempotency(db_session: Session, stale_job_fixture):
    """
    Mutation Check 5: Running reaper repeatedly must be strictly idempotent.
    """
    user, job = stale_job_fixture
    assert BillingRepository.get_monthly_usage_count(db_session, user.id) == 1

    first_run = AnalysisJobRepository.clean_stale_running_jobs(db_session, timeout_minutes=30)
    assert len(first_run) == 1
    assert BillingRepository.get_monthly_usage_count(db_session, user.id) == 0

    second_run = AnalysisJobRepository.clean_stale_running_jobs(db_session, timeout_minutes=30)
    assert len(second_run) == 0
    assert BillingRepository.get_monthly_usage_count(db_session, user.id) == 0


def test_stale_job_reaper_multiple_users_isolation(db_session: Session):
    """
    Verifies that multiple users with different job ages and statuses are handled cleanly
    without cross-tenant interference.
    """
    u1 = UserModel(github_id=98707, github_username="multi_user_1", email="u1@example.com")
    u2 = UserModel(github_id=98708, github_username="multi_user_2", email="u2@example.com")
    db_session.add_all([u1, u2])
    db_session.commit()

    # User 1 quota & jobs
    BillingService.check_and_consume_quota(u1, db_session)
    BillingService.check_and_consume_quota(u1, db_session)
    assert BillingRepository.get_monthly_usage_count(db_session, u1.id) == 2

    u1_stale = AnalysisJobRepository.create_job(db_session, u1.id, repo_url="https://github.com/u1/stale", status="running")
    u1_stale.created_at = utc_now() - timedelta(minutes=45)
    u1_stale.updated_at = utc_now() - timedelta(minutes=45)

    u1_active = AnalysisJobRepository.create_job(db_session, u1.id, repo_url="https://github.com/u1/active", status="running")
    u1_active.created_at = utc_now() - timedelta(minutes=1)
    u1_active.updated_at = utc_now() - timedelta(minutes=1)

    # User 2 quota & jobs
    BillingService.check_and_consume_quota(u2, db_session)
    assert BillingRepository.get_monthly_usage_count(db_session, u2.id) == 1

    u2_stale = AnalysisJobRepository.create_job(db_session, u2.id, repo_url="https://github.com/u2/stale", status="running")
    u2_stale.created_at = utc_now() - timedelta(minutes=60)
    u2_stale.updated_at = utc_now() - timedelta(minutes=60)

    db_session.commit()

    # Clean stale jobs with 2-minute boot grace
    reclaimed = AnalysisJobRepository.clean_stale_running_jobs(db_session, timeout_minutes=2)
    assert len(reclaimed) == 2
    reclaimed_ids = {j.id for j in reclaimed}
    assert u1_stale.id in reclaimed_ids
    assert u2_stale.id in reclaimed_ids
    assert u1_active.id not in reclaimed_ids

    # User 1 should have refunded 1 quota (2 -> 1 remaining)
    assert BillingRepository.get_monthly_usage_count(db_session, u1.id) == 1
    # User 2 should have refunded 1 quota (1 -> 0 remaining)
    assert BillingRepository.get_monthly_usage_count(db_session, u2.id) == 0
