"""
Tests for Backtrace Dashboard Redesign (Prompt 8 Rebuild).

Covers:
1. Grouping query returns one row for three runs of the same repo with runs=3.
2. Delete route refuses another user's job (403 Forbidden) and deletes own job.
3. Dashboard template layout elements:
   - H1 "Analyze a repository" & subtitle "Paste a GitHub link and get a step-by-step guide to understand the code."
   - Form: big input "https://github.com/owner/repo" & primary button "Analyze repository"
   - Collapsible "Advanced options" with Branch & Subdirectory
   - Sample chip: fills input
   - Quota: one line and one bar (Prompt 7), no badge
   - "Upgrade to Pro" secondary outlined button (only when billing enabled)
   - History grouped by repo URL: latest run status, date via <time>, learning progress ("2 of 7 done"), "3 runs" badge
   - Primary action "Open report" on one line (white-space: nowrap)
   - Overflow menu "..." with "Delete" (confirm dialog, POST delete route)
   - Search input filtering rows client-side by repo name
   - Removal of "RE-ANALYZED (3X)" and "FREE (3/5)" badge from dashboard
4. Playwright interactive check:
   - Sample chip click fills the input field
   - Search input filters history rows client-side
"""

import os
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user_optional, get_db
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, MilestoneAttemptModel, UserModel
from app.security.auth import create_access_token
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.billing_repository import BillingRepository
from app.storage.user_repository import UserRepository
from app.ui.components import dashboard_view


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
def test_db_session(test_db):
    TestingSessionLocal, _ = test_db
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


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


# =============================================================================
# 1. Grouping Query Test
# =============================================================================

def test_grouping_query_returns_one_row_for_three_runs_with_runs_3(test_db_session):
    """
    Test that the grouping query groups jobs by repo URL, returning one row
    for multiple runs of the same repo, with runs=3 and returning the latest run.
    """
    user = UserModel(github_id=12345, github_username="grouper_dev", email="grouper@example.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    repo_a = "https://github.com/fastapi/fastapi"
    repo_b = "https://github.com/encode/uvicorn"

    # Insert 3 runs for repo A at different timestamps
    job_a1 = AnalysisJobModel(
        user_id=user.id,
        repo_url=repo_a,
        repo_name="fastapi",
        status="completed",
        resolved_sha="sha_run_1",
        run_id="run_a1",
        created_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    job_a2 = AnalysisJobModel(
        user_id=user.id,
        repo_url=repo_a,
        repo_name="fastapi",
        status="completed",
        resolved_sha="sha_run_2",
        run_id="run_a2",
        created_at=datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc),
    )
    job_a3 = AnalysisJobModel(
        user_id=user.id,
        repo_url=repo_a,
        repo_name="fastapi",
        status="completed",
        resolved_sha="sha_run_3",
        run_id="run_a3",
        created_at=datetime(2026, 1, 3, 10, 0, 0, tzinfo=timezone.utc),
    )

    # Insert 1 run for repo B
    job_b1 = AnalysisJobModel(
        user_id=user.id,
        repo_url=repo_b,
        repo_name="uvicorn",
        status="completed",
        resolved_sha="sha_b1",
        run_id="run_b1",
        created_at=datetime(2026, 1, 4, 10, 0, 0, tzinfo=timezone.utc),
    )

    test_db_session.add_all([job_a1, job_a2, job_a3, job_b1])
    test_db_session.commit()
    test_db_session.refresh(job_a3)
    test_db_session.refresh(job_b1)

    # Execute grouped query
    grouped_jobs = AnalysisJobRepository.get_grouped_jobs_for_user(test_db_session, user.id)

    # Must return exactly 2 rows (one for repo_a, one for repo_b)
    assert len(grouped_jobs) == 2, f"Expected 2 grouped rows, got {len(grouped_jobs)}"

    # Find row for repo_a
    repo_a_row = next(j for j in grouped_jobs if j.repo_url == repo_a)
    assert repo_a_row.runs == 3, f"Expected runs=3 for repo_a, got {repo_a_row.runs}"
    assert repo_a_row["runs"] == 3
    # Check that it represents the latest run (job_a3)
    assert repo_a_row.id == job_a3.id
    assert repo_a_row.resolved_sha == "sha_run_3"

    # Find row for repo_b
    repo_b_row = next(j for j in grouped_jobs if j.repo_url == repo_b)
    assert repo_b_row.runs == 1, f"Expected runs=1 for repo_b, got {repo_b_row.runs}"
    assert repo_b_row.id == job_b1.id


# =============================================================================
# 2. Delete Route Refuses Another User's Job (403 Forbidden)
# =============================================================================

def test_delete_route_refuses_another_users_job_403(client, test_db_session):
    """
    Test that the POST delete route refuses another user's job with 403 Forbidden,
    and allows the owner to delete their own job.
    """
    # User 1 (owner)
    user_owner = UserModel(github_id=101, github_username="owner_user", email="owner@test.com")
    # User 2 (attacker / other user)
    user_other = UserModel(github_id=202, github_username="other_user", email="other@test.com")

    test_db_session.add_all([user_owner, user_other])
    test_db_session.commit()
    test_db_session.refresh(user_owner)
    test_db_session.refresh(user_other)

    # Create job belonging to user_owner
    job = AnalysisJobModel(
        user_id=user_owner.id,
        repo_url="https://github.com/owner/secret-repo",
        repo_name="secret-repo",
        status="completed",
        run_id="run_secret_1",
    )
    test_db_session.add(job)
    test_db_session.commit()
    test_db_session.refresh(job)

    # 1. Attempt delete as user_other -> MUST RETURN 403 FORBIDDEN
    app.dependency_overrides[get_current_user_optional] = lambda: user_other
    app.dependency_overrides[get_db] = lambda: test_db_session

    resp_other = client.post(f"/analyses/{job.id}/delete", follow_redirects=False)
    assert resp_other.status_code == 403, f"Expected 403 Forbidden, got {resp_other.status_code}"

    # Verify job still exists in DB
    refreshed_job = AnalysisJobRepository.get_job_by_id(test_db_session, job.id)
    assert refreshed_job is not None, "Job should not have been deleted by non-owner"

    # 2. Attempt delete as user_owner -> MUST SUCCEED (303 redirect to /dashboard or 200)
    app.dependency_overrides[get_current_user_optional] = lambda: user_owner

    resp_owner = client.post(f"/analyses/{job.id}/delete", follow_redirects=False)
    assert resp_owner.status_code in (200, 302, 303), f"Expected 303/302/200, got {resp_owner.status_code}"
    if resp_owner.status_code in (302, 303):
        assert "/dashboard" in resp_owner.headers["location"]

    # Verify job is now deleted from DB
    deleted_job = AnalysisJobRepository.get_job_by_id(test_db_session, job.id)
    assert deleted_job is None, "Job should be deleted from DB by owner"


# =============================================================================
# 3. Dashboard UI Layout & Elements
# =============================================================================

def test_dashboard_ui_layout_and_elements():
    """
    Verify all elements required by Prompt 8 redesign are present:
    1. H1 "Analyze a repository" and subtitle
    2. Big input "https://github.com/owner/repo" and primary button "Analyze repository"
    3. Collapsible "Advanced options" with Branch and Subdirectory
    4. Sample chip
    5. Quota: one line and one bar, NO badge ("badge-free" or "FREE (3/5)")
    6. "Upgrade to Pro" secondary outlined button (only when billing enabled)
    7. History grouped by repo: latest run status, date via <time>, learning progress, "3 runs" badge
    8. Primary action "Open report" with white-space: nowrap
    9. Overflow menu "..." with "Delete" confirm dialog
    10. Search input for client-side filtering
    11. Removal of "RE-ANALYZED (3X)" and "FREE (3/5)" badge
    """
    user = UserModel(id=1, github_id=1, github_username="tester", email="test@example.com")

    # Mock a grouped job with 3 runs and milestone progress (2 of 7 done)
    class MockJob:
        id = 42
        repo_url = "https://github.com/expressjs/express"
        repo_name = "express"
        status = "completed"
        execution_time_seconds = 12.4
        created_at = datetime(2026, 10, 24, 2, 30, 0, tzinfo=timezone.utc)
        runs = 3
        graph_data = {"nodes": [{"tier": 1}, {"tier": 2}, {"tier": 3}, {"tier": 4}, {"tier": 5}, {"tier": 6}, {"tier": 7}]}
        markdown_output = None
        milestone_attempts = [
            type("Attempt", (), {"status": "structurally_verified"}),
            type("Attempt", (), {"status": "structurally_verified"}),
            type("Attempt", (), {"status": "in_progress"}),
        ]
        def __getitem__(self, item):
            return getattr(self, item)

    mock_job = MockJob()

    # Case A: Billing enabled (tier="free", usage=3, quota=5)
    os.environ["STRIPE_BILLING_ENABLED"] = "true"
    try:
        html = dashboard_view(
            current_user=user,
            billing_status={"tier": "free", "monthly_usage": 3, "monthly_quota": 5},
            past_jobs=[mock_job],
        )

        # 1. H1 and Subtitle
        assert "Analyze a repository" in html
        assert "Paste a GitHub link and get a step-by-step guide to understand the code." in html

        # 2. Form input & button
        assert 'placeholder="https://github.com/owner/repo"' in html
        assert "Analyze repository" in html
        assert 'id="analyze-button"' in html

        # 3. Collapsible Advanced Options
        assert "Advanced options" in html
        assert 'name="commit_ref"' in html
        assert 'name="subpath"' in html

        # 4. Sample chip
        assert "expressjs/express" in html
        assert "sample-chip" in html

        # 5. Quota line and meter (one line and one bar, no badge)
        assert "3 of 5 analyses used this month" in html
        assert 'class="meter"' in html
        quota_part = html[html.find('id="quota-indicator-card"'):html.find('class="history-section"')]
        assert "badge" not in quota_part, "Quota indicator must not have a badge"
        assert '<span class="badge badge-free">' not in html

        # 6. Upgrade to Pro secondary outlined button
        assert "Upgrade to Pro" in html
        assert 'id="upgrade-pro-btn"' in html

        # 7. History row with 3 runs, date via <time>, learning progress 2 of 7 done
        assert "3 runs" in html
        assert "<time" in html
        assert "2 of 7 done" in html

        # 8. Primary action "Open report" on one line (white-space: nowrap)
        assert "Open report" in html
        assert "white-space: nowrap" in html

        # 9. Overflow menu with Delete and confirm dialog
        assert "..." in html or "&hellip;" in html
        assert "/analyses/42/delete" in html
        assert "confirm(" in html

        # 10. Client-side search input
        assert 'id="repo-search-input"' in html

        # 11. Absence of old badges from history rows
        history_part = html[html.find('class="history-section"'):]
        assert "RE-ANALYZED" not in history_part
        assert "FREE (3/5)" not in history_part
        assert "badge-free" not in history_part

    finally:
        os.environ.pop("STRIPE_BILLING_ENABLED", None)

    # Case B: Billing disabled -> "Upgrade to Pro" button must NOT appear
    os.environ["STRIPE_BILLING_ENABLED"] = "false"
    try:
        html_no_billing = dashboard_view(
            current_user=user,
            billing_status={"tier": "free", "monthly_usage": 1, "monthly_quota": 5},
            past_jobs=[mock_job],
        )
        assert "Upgrade to Pro" not in html_no_billing
    finally:
        os.environ.pop("STRIPE_BILLING_ENABLED", None)


# =============================================================================
# 4. Playwright Browser Interactive Verification
# =============================================================================

def test_sample_chip_and_search_filter_playwright(tmp_path):
    """
    Use Playwright to verify:
    1. Clicking the sample chip fills the #repo-url-input.
    2. Typing in #repo-search-input dynamically filters rows client-side.
    """
    from playwright.sync_api import sync_playwright

    user = UserModel(id=1, github_id=1, github_username="tester", email="test@example.com")

    class MockJob1:
        id = 101
        repo_url = "https://github.com/expressjs/express"
        repo_name = "express"
        status = "completed"
        execution_time_seconds = 5.2
        created_at = datetime(2026, 10, 24, 1, 0, 0, tzinfo=timezone.utc)
        runs = 2
        graph_data = None
        markdown_output = None
        milestone_attempts = []
        def __getitem__(self, item):
            return getattr(self, item)

    class MockJob2:
        id = 102
        repo_url = "https://github.com/pallets/flask"
        repo_name = "flask"
        status = "completed"
        execution_time_seconds = 8.1
        created_at = datetime(2026, 10, 24, 2, 0, 0, tzinfo=timezone.utc)
        runs = 1
        graph_data = None
        markdown_output = None
        milestone_attempts = []
        def __getitem__(self, item):
            return getattr(self, item)

    html = dashboard_view(
        current_user=user,
        billing_status={"tier": "free", "monthly_usage": 2, "monthly_quota": 5},
        past_jobs=[MockJob1(), MockJob2()],
    )

    # Save to a temporary HTML file to load in Playwright
    html_file = tmp_path / "dashboard_test.html"
    html_file.write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(html_file.as_uri())

        # 1. Test sample chip interaction
        input_elem = page.locator("#repo-url-input")
        assert input_elem.input_value() == ""

        sample_chip = page.locator("#sample-chip-btn")
        sample_chip.click()
        assert input_elem.input_value() == "https://github.com/expressjs/express"

        # 2. Test search filter
        rows = page.locator(".history-row")
        assert rows.count() == 2

        search_input = page.locator("#repo-search-input")
        search_input.fill("flask")

        # Row 1 (express) should now be hidden
        assert not rows.nth(0).is_visible()
        # Row 2 (flask) should remain visible
        assert rows.nth(1).is_visible()

        # Clear search
        search_input.fill("")
        assert rows.nth(0).is_visible()
        assert rows.nth(1).is_visible()

        browser.close()


# =============================================================================
# 5. Restored Core Dashboard State Tests (Adapted to Prompt 8 Redesign)
# =============================================================================

def test_dashboard_unauthenticated_redirect(client):
    """Unauthenticated users visiting /dashboard must be redirected to /login."""
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_dashboard_free_user_empty_state(client, create_user):
    """Free user with no jobs sees empty state and real quota metadata."""
    user = create_user(github_id=888001, username="dash_user1")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text

    # Editorial Header
    assert "Analyze a repository" in html
    assert "Paste a GitHub link and get a step-by-step guide" in html

    # Main Card & Sample chip
    assert "https://github.com/expressjs/express" in html

    # Empty State Copy
    assert "No analyses yet" in html
    assert "0 of 5 analyses used this month" in html

    # Inverted: badges / legacy strings intentionally removed in Prompt 8 redesign
    assert "0 / 5 JOBS ALLOTTED" not in html
    assert "FREE (3/5)" not in html
    assert "ARCHITECTURE REPORT REPOSITORY PARSING" not in html
    assert "Detailed Syntax Tree Analysis" not in html
    assert "Automatic Tier Grouping" not in html
    assert "RE-ANALYZED" not in html


def test_dashboard_populated_state(client, create_user, test_db):
    """Dashboard correctly lists completed, running, and failed jobs with accurate action triggers."""
    user = create_user(github_id=888001, username="dash_user1")
    SessionLocal, _ = test_db
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with SessionLocal() as session:
        j1 = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/expressjs/express",
            repo_name="express",
            status="completed",
        )
        j2 = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/pallets/flask",
            repo_name="flask",
            status="running",
        )
        j3 = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/django/django",
            repo_name="django",
            status="failed",
        )
        j1_id, j2_id, j3_id = j1.id, j2.id, j3.id

    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text

    # Verify rows & actions adapted to new markup
    assert f"/report/{j1_id}" in html
    assert "Open report" in html
    assert f"/progress/{j2_id}" in html
    assert "Track progress" in html
    assert f"/analyses/{j3_id}/retry" in html
    assert "Retry analysis" in html or "Retry" in html

    # Inverted: removed badges
    assert "RE-ANALYZED (3X)" not in html
    assert "FREE (3/5)" not in html


def test_dashboard_paid_user_state(client, create_user, test_db):
    """Paid user sees pro tier quota status and manage billing option."""
    from datetime import datetime, timedelta, timezone
    user = create_user(github_id=888001, username="dash_user1")
    SessionLocal, _ = test_db
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    future_end = datetime.now(timezone.utc) + timedelta(days=30)
    with SessionLocal() as session:
        BillingRepository.upsert_subscription(
            session=session,
            user_id=user.id,
            stripe_customer_id="cus_test_paid_user",
            stripe_subscription_id="sub_test_paid_user",
            status="active",
            current_period_end=future_end.replace(tzinfo=None),
        )
        session.commit()

    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text

    # Quota line for paid / pro user
    assert "Unlimited analyses used this month" in html

    # Inverted: badges and upgrade buttons intentionally removed for paid user
    assert "PRO TIER" not in html
    assert "UNLIMITED ANALYSIS JOBS" not in html
    assert "FREE (3/5)" not in html
    assert "Upgrade to Pro" not in html
