"""Tests for Frontend v2 Dashboard View (FRONTEND_VERSION=2)."""

import html
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import uvicorn
from playwright.sync_api import sync_playwright
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user_optional, get_db
from app.db.session import Base
from app.frontend2.components import dashboard_view
from app.main import app
from app.models.db import AnalysisJobModel, UserModel
from app.security.auth import create_access_token
from app.storage.analysis_job_repository import AnalysisJobRepository


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
def mock_user():
    return UserModel(
        id=1,
        github_id=77001,
        github_username="f2_dash_tester",
        email="f2_dash@example.com",
    )


class TestFrontend2DashboardRendering:
    """Unit tests for Frontend v2 Dashboard rendering, escaping, and form parity."""

    def test_renders_each_state_from_fixtures(self, mock_user, monkeypatch):
        """Dashboard renders running, ready, failed, and cancelled states with accurate actions."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        job_running = AnalysisJobModel(
            id=101,
            user_id=mock_user.id,
            repo_url="https://github.com/org/running-repo",
            repo_name="running-repo",
            status="running",
            created_at=datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc),
        )

        job_ready = AnalysisJobModel(
            id=102,
            user_id=mock_user.id,
            repo_url="https://github.com/org/ready-repo",
            repo_name="ready-repo",
            status="completed",
            created_at=datetime(2026, 10, 25, 11, 0, 0, tzinfo=timezone.utc),
            execution_time_seconds=6.4,
            graph_output_json='{"nodes": [{"id": "n1", "tier": 1}, {"id": "n2", "tier": 2}]}',
        )
        job_ready.runs = 2

        job_failed = AnalysisJobModel(
            id=103,
            user_id=mock_user.id,
            repo_url="https://github.com/org/failed-repo",
            repo_name="failed-repo",
            status="failed",
            error_message="Fatal: could not read Username for 'https://github.com' token=secret",
            created_at=datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc),
        )

        job_cancelled = AnalysisJobModel(
            id=104,
            user_id=mock_user.id,
            repo_url="https://github.com/org/cancelled-repo",
            repo_name="cancelled-repo",
            status="cancelled",
            created_at=datetime(2026, 10, 25, 9, 0, 0, tzinfo=timezone.utc),
        )

        html_out = dashboard_view(
            current_user=mock_user,
            billing_status={"tier": "free", "monthly_usage": 3, "monthly_quota": 5},
            past_jobs=[job_running, job_ready, job_failed, job_cancelled],
        )

        # 1. Running state
        assert "indeterminate-bar" in html_out
        assert "Analyzing…" in html_out
        assert "Started " in html_out
        assert "/progress/101" in html_out
        assert "Track progress" in html_out

        # 2. Ready state
        assert "Ready" in html_out
        assert "Open report" in html_out
        assert "/report/102" in html_out
        assert "2 milestones" in html_out
        assert "milestones completed" in html_out or "done" in html_out
        assert "2 runs" in html_out

        # 3. Failed state
        assert "Failed:" in html_out
        assert "couldn&#x27;t access this repository" in html_out or "couldn't access this repository" in html_out
        assert "/analyses/103/retry" in html_out
        assert "Edit link" in html_out
        assert "Retry" in html_out
        # Sensitive credentials leaked in raw error must not be rendered
        assert "Fatal" not in html_out
        assert "Username" not in html_out
        assert "token=secret" not in html_out

        # 4. Cancelled state
        assert "Cancelled" in html_out
        assert "You cancelled this analysis." in html_out
        assert "/analyses/104/retry" in html_out

        # 5. Overflow delete menu for each job
        for j_id in [101, 102, 103, 104]:
            assert f"/analyses/{j_id}/delete" in html_out
            assert "confirm(" in html_out

        # 6. Quota line
        assert "Free · 3 of 5 analyses this month" in html_out
        assert "Resets " in html_out

    def test_hostile_repo_name_and_error_message_escaped(self, mock_user, monkeypatch):
        """XSS injection payloads in repo_name, repo_url, and error_message are strictly sanitized."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        payload = '<img src=x onerror=alert("xss")>"><svg onload=alert(1)>'
        escaped_payload = html.escape(payload, quote=True)

        job_hostile = AnalysisJobModel(
            id=201,
            user_id=mock_user.id,
            repo_url=f"https://github.com/evil/{payload}",
            repo_name=f"repo-{payload}",
            status="failed",
            error_message=f"Clone failed: {payload}",
        )

        html_out = dashboard_view(
            current_user=mock_user,
            billing_status={"tier": "free", "monthly_usage": 1, "monthly_quota": 5},
            past_jobs=[job_hostile],
        )

        assert "<img src=x onerror" not in html_out
        assert "<svg onload" not in html_out
        assert " onmouseover=" not in html_out
        assert escaped_payload in html_out

    def test_form_field_names_equal_frontend1(self, mock_user, monkeypatch):
        """Form attributes and inputs must strictly match frontend1 for form handling parity."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        html_out = dashboard_view(
            current_user=mock_user,
            billing_status={"tier": "free", "monthly_usage": 0, "monthly_quota": 5},
            past_jobs=[],
        )

        # Form action & method
        assert 'action="/analyses/submit"' in html_out
        assert 'method="POST"' in html_out
        assert 'id="reconstruct-form"' in html_out

        # Field names
        assert 'name="repo_url"' in html_out
        assert 'name="commit_ref"' in html_out
        assert 'name="subpath"' in html_out

        # Crucial element IDs
        assert 'id="analyze-button"' in html_out
        assert 'id="repo-url-input"' in html_out
        assert 'id="repo-search-input"' in html_out
        assert 'id="quota-indicator-card"' in html_out
        assert 'id="sample-chip-btn"' in html_out
        assert 'id="advanced-options-details"' in html_out
        assert 'id="cold-start-banner"' in html_out

    def test_not_available_elements_are_absent(self, mock_user, monkeypatch):
        """Elements confirmed as NOT AVAILABLE in Step 1 must never be rendered in frontend2."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        job_running = AnalysisJobModel(
            id=301,
            user_id=mock_user.id,
            repo_url="https://github.com/org/run",
            repo_name="run",
            status="running",
        )
        job_cancelled = AnalysisJobModel(
            id=302,
            user_id=mock_user.id,
            repo_url="https://github.com/org/canc",
            repo_name="canc",
            status="cancelled",
        )

        html_out = dashboard_view(
            current_user=mock_user,
            billing_status={"tier": "free", "monthly_usage": 2, "monthly_quota": 5},
            past_jobs=[job_running, job_cancelled],
        )

        assert "Step 3 of 4" not in html_out
        assert "Step N of 4" not in html_out
        assert "Step 1 of 4" not in html_out
        assert "18 files" not in html_out
        assert "View all" not in html_out
        assert "Not enough code" not in html_out
        assert "Only 1 supported file found" not in html_out
        assert "You cancelled this analysis at step" not in html_out


class TestFrontend2DashboardPlaywright:
    """Browser verification using Playwright on a live uvicorn server at multiple viewport widths."""

    def test_dashboard_playwright_responsiveness_and_touch_targets(self, test_db, monkeypatch):
        """
        At viewports 390, 768, 1440:
        1. No horizontal scrolling (scrollWidth <= innerWidth).
        2. Status pills remain strictly single-line.
        3. At 390px, all interactive tap targets have height >= 44px.
        4. Screenshots saved to scratch/f2_dashboard/.
        """
        monkeypatch.setenv("FRONTEND_VERSION", "2")
        os.makedirs("scratch/f2_dashboard", exist_ok=True)

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

        with TestingSessionLocal() as session:
            user = UserModel(
                github_id=99099,
                github_username="pw_dash_user",
                email="pw_dash@example.com",
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            user_id = user.id

            j1 = AnalysisJobRepository.create_job(
                session=session,
                user_id=user_id,
                repo_url="https://github.com/expressjs/express-with-a-very-long-repository-name-that-must-safely-wrap",
                repo_name="express-with-a-very-long-repository-name-that-must-safely-wrap",
                status="running",
            )
            j2 = AnalysisJobRepository.create_job(
                session=session,
                user_id=user_id,
                repo_url="https://github.com/tiangolo/fastapi",
                repo_name="fastapi",
                status="completed",
            )
            AnalysisJobRepository.update_job_status(
                session=session,
                job_id=j2.id,
                status="completed",
                graph_data={"nodes": [{"id": "1", "tier": 1}, {"id": "2", "tier": 2}]},
            )
            j3 = AnalysisJobRepository.create_job(
                session=session,
                user_id=user_id,
                repo_url="https://github.com/encode/starlette",
                repo_name="starlette",
                status="failed",
            )
            AnalysisJobRepository.update_job_status(
                session=session,
                job_id=j3.id,
                status="failed",
                error_message="Repository not found or access denied",
            )
            j4 = AnalysisJobRepository.create_job(
                session=session,
                user_id=user_id,
                repo_url="https://github.com/pallets/flask",
                repo_name="flask",
                status="cancelled",
            )
            session.commit()

        token = create_access_token(
            user_id=user_id,
            github_id=99099,
            github_username="pw_dash_user",
        )

        def override_get_current_user():
            with TestingSessionLocal() as s:
                u = s.query(UserModel).filter_by(id=user_id).first()
                if u:
                    s.refresh(u)
                    s.expunge(u)
                return u

        app.dependency_overrides[get_current_user_optional] = override_get_current_user
        app.dependency_overrides[get_db] = override_get_db

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                context.add_cookies([
                    {
                        "name": "access_token",
                        "value": token,
                        "domain": "127.0.0.1",
                        "path": "/",
                    }
                ])
                page = context.new_page()

                widths = [390, 768, 1440]

                for width in widths:
                    page.set_viewport_size({"width": width, "height": 844})
                    page.goto(f"http://127.0.0.1:{port}/dashboard", wait_until="networkidle")

                    # 1. Assert no horizontal scrolling: scrollWidth <= innerWidth
                    scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
                    inner_width = page.evaluate("() => window.innerWidth")
                    assert scroll_width <= inner_width, f"Horizontal scroll detected at width {width}: {scroll_width} > {inner_width}"

                    # 2. Assert status pills are single-line (white-space: nowrap)
                    pills = page.locator(".status-pill")
                    pill_count = pills.count()
                    assert pill_count > 0, "No status pills found on dashboard"
                    for idx in range(pill_count):
                        pill = pills.nth(idx)
                        ws = pill.evaluate("el => window.getComputedStyle(el).whiteSpace")
                        assert ws == "nowrap", f"Pill {idx} at width {width} does not have white-space: nowrap (has {ws})"

                    # 3. Capture screenshot
                    shot_path = os.path.join("scratch", "f2_dashboard", f"dashboard_{width}.png")
                    page.screenshot(path=shot_path, full_page=False)

                    # 4. At 390px, verify interactive tap targets have height >= 44px
                    if width == 390:
                        interactive_selectors = [
                            "#analyze-button",
                            ".sample-chip",
                            "#adv-toggle-btn",
                            ".history-card a.btn",
                            ".history-card button",
                            ".overflow-btn",
                        ]
                        for sel in interactive_selectors:
                            elements = page.locator(sel)
                            count = elements.count()
                            for i in range(count):
                                el = elements.nth(i)
                                if el.is_visible():
                                    box = el.bounding_box()
                                    if box:
                                        assert box["height"] >= 43.5, f"Interactive target {sel} #{i} height {box['height']} < 44px"

                browser.close()
        finally:
            server.should_exit = True
            server_thread.join(timeout=3)
            app.dependency_overrides.clear()

    def test_edit_link_clicks_fill_repo_url_input(self, test_db, monkeypatch):
        """Clicking 'Edit link' on a failed job fills #repo-url-input with that job's repo URL and focuses it."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")
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

        with TestingSessionLocal() as session:
            user = UserModel(
                github_id=99098,
                github_username="pw_edit_user",
                email="pw_edit@example.com",
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            user_id = user.id

            j_failed = AnalysisJobRepository.create_job(
                session=session,
                user_id=user_id,
                repo_url="https://github.com/encode/starlette",
                repo_name="starlette",
                status="failed",
            )
            AnalysisJobRepository.update_job_status(
                session=session,
                job_id=j_failed.id,
                status="failed",
                error_message="Repository not found or access denied",
            )
            session.commit()

        token = create_access_token(
            user_id=user_id,
            github_id=99098,
            github_username="pw_edit_user",
        )

        def override_get_current_user():
            with TestingSessionLocal() as s:
                u = s.query(UserModel).filter_by(id=user_id).first()
                if u:
                    s.refresh(u)
                    s.expunge(u)
                return u

        app.dependency_overrides[get_current_user_optional] = override_get_current_user
        app.dependency_overrides[get_db] = override_get_db

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                context.add_cookies([
                    {
                        "name": "access_token",
                        "value": token,
                        "domain": "127.0.0.1",
                        "path": "/",
                    }
                ])
                page = context.new_page()
                page.set_viewport_size({"width": 1280, "height": 800})
                page.goto(f"http://127.0.0.1:{port}/dashboard", wait_until="networkidle")

                input_el = page.locator("#repo-url-input")
                assert input_el.input_value() == ""

                edit_button = page.locator(".edit-link-btn").first
                assert edit_button.is_visible()
                edit_button.click()

                # Verify #repo-url-input is filled with the failed job repo URL
                assert input_el.input_value() == "https://github.com/encode/starlette"

                # Verify #repo-url-input is focused
                focused_id = page.evaluate("() => document.activeElement ? document.activeElement.id : null")
                assert focused_id == "repo-url-input"

                browser.close()
        finally:
            server.should_exit = True
            server_thread.join(timeout=3)
            app.dependency_overrides.clear()
