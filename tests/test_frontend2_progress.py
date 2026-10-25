"""Tests for Frontend v2 Progress View (FRONTEND_VERSION=2)."""

import html
import json
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
from app.frontend2.components import map_stage_to_phase, progress_view
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
        github_id=88001,
        github_username="f2_prog_tester",
        email="f2_prog@example.com",
    )


class TestFrontend2ProgressRendering:
    """Unit tests for Frontend v2 Progress view rendering, states, escaping, and required/dropped elements."""

    def test_renders_each_state_from_fixtures(self, mock_user, monkeypatch):
        """Progress renders running, completed, failed, and cancelled states correctly from fixtures."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        # 1. RUNNING STATE
        job_running = AnalysisJobModel(
            id=201,
            user_id=mock_user.id,
            repo_url="https://github.com/acme/rocket-engine",
            repo_name="rocket-engine",
            status="running",
            created_at=datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc),
        )
        html_running = progress_view(job_running, current_user=mock_user)

        assert "rocket-engine" in html_running
        assert 'id="active-card"' in html_running
        assert 'id="active-sentence"' in html_running
        assert 'id="active-card-timer"' in html_running
        assert 'id="progress-bar-fill"' in html_running
        assert 'id="cancel-trigger-wrapper"' in html_running
        assert 'style="display: block;"' in html_running or 'style="display: none;"' not in html_running.split('id="active-card"')[1][:50]
        assert 'id="report-ready-card" style="display: none;"' in html_running
        assert 'id="failed-card" style="display: none;"' in html_running
        assert 'id="cancelled-card" style="display: none;"' in html_running
        assert "Step 1 of 4" in html_running

        # 2. COMPLETED STATE with real counts
        job_completed = AnalysisJobModel(
            id=202,
            user_id=mock_user.id,
            repo_url="https://github.com/acme/rocket-engine",
            repo_name="rocket-engine",
            status="completed",
            created_at=datetime(2026, 10, 25, 11, 0, 0, tzinfo=timezone.utc),
            execution_time_seconds=18.5,
            report_markdown=(
                "# Architectural Reverse-Engineering Report: `rocket-engine`\n\n"
                "*Synthesized at: 2026-10-25 11:00:18 UTC*\n\n"
                "## Overview\n"
                "- **Primary Language**: `Python`\n"
                "- **Total Analyzed Files**: `128`\n"
                "- **Domain Categories**: `4`\n"
                "- **Entry Point Files**: `src/main.py, src/cli.py`\n"
            ),
        )
        html_completed = progress_view(job_completed, current_user=mock_user)

        assert 'id="report-ready-card" style="display: block;"' in html_completed
        assert 'id="ready-files-count" class="ready-stat-value">128</div>' in html_completed
        assert 'id="ready-modules-count" class="ready-stat-value">4</div>' in html_completed
        assert 'id="ready-entry-count" class="ready-stat-value">2</div>' in html_completed
        assert 'href="/report/202" class="btn btn-primary" id="start-learning-btn"' in html_completed
        assert 'href="/report/202" class="btn btn-secondary" id="open-map-btn"' in html_completed
        assert 'id="active-card" style="display: none;"' in html_completed
        assert 'id="cancel-trigger-wrapper" style="display: none;"' in html_completed

        # Check all 4 segmented bars have 'done'
        assert '<div class="segment-bar done" id="segment-bar-1"></div>' in html_completed
        assert '<div class="segment-bar done" id="segment-bar-2"></div>' in html_completed
        assert '<div class="segment-bar done" id="segment-bar-3"></div>' in html_completed
        assert '<div class="segment-bar done" id="segment-bar-4"></div>' in html_completed

        # 3. COMPLETED STATE with real 0 entry points
        job_completed_zero_entry = AnalysisJobModel(
            id=203,
            user_id=mock_user.id,
            repo_url="https://github.com/acme/library",
            repo_name="library",
            status="completed",
            created_at=datetime(2026, 10, 25, 11, 0, 0, tzinfo=timezone.utc),
            report_markdown=(
                "# Architectural Reverse-Engineering Report: `library`\n\n"
                "## Overview\n"
                "- **Primary Language**: `Go`\n"
                "- **Total Analyzed Files**: `45`\n"
                "- **Domain Categories**: `2`\n"
                "- **Entry Point Files**: `None`\n"
            ),
        )
        html_zero = progress_view(job_completed_zero_entry, current_user=mock_user)
        assert 'id="ready-entry-count" class="ready-stat-value">0</div>' in html_zero

        # 4. COMPLETED STATE with missing entry points
        job_completed_missing_entry = AnalysisJobModel(
            id=204,
            user_id=mock_user.id,
            repo_url="https://github.com/acme/unknown",
            repo_name="unknown",
            status="completed",
            created_at=datetime(2026, 10, 25, 11, 0, 0, tzinfo=timezone.utc),
            report_markdown="# Architectural Reverse-Engineering Report: `unknown`\n\nNo overview",
        )
        html_missing = progress_view(job_completed_missing_entry, current_user=mock_user)
        assert 'id="ready-entry-count" class="ready-stat-value">—</div>' in html_missing

        # 5. FAILED STATE
        job_failed = AnalysisJobModel(
            id=205,
            user_id=mock_user.id,
            repo_url="https://github.com/acme/private-repo",
            repo_name="private-repo",
            status="failed",
            created_at=datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc),
            error_message="fatal: could not read Username for 'https://github.com': No such device or address",
        )
        html_failed = progress_view(job_failed, current_user=mock_user)

        assert 'id="failed-card" style="display: block;"' in html_failed
        assert 'id="failed-reason-text"' in html_failed
        assert 'action="/analyses/205/retry" method="POST"' in html_failed
        assert 'id="retry-btn"' in html_failed
        assert 'href="/dashboard"' in html_failed
        assert 'Back to dashboard' in html_failed
        assert 'id="active-card" style="display: none;"' in html_failed

        # 6. CANCELLED STATE
        job_cancelled = AnalysisJobModel(
            id=206,
            user_id=mock_user.id,
            repo_url="https://github.com/acme/cancelled-job",
            repo_name="cancelled-job",
            status="cancelled",
            created_at=datetime(2026, 10, 25, 9, 0, 0, tzinfo=timezone.utc),
        )
        html_cancelled = progress_view(job_cancelled, current_user=mock_user)

        assert 'id="cancelled-card" style="display: block;"' in html_cancelled
        assert "Analysis cancelled" in html_cancelled
        assert "This analysis was cancelled." in html_cancelled
        assert 'href="/dashboard"' in html_cancelled
        assert 'id="active-card" style="display: none;"' in html_cancelled

    def test_hostile_repo_name_and_error_text_escaped(self, mock_user, monkeypatch):
        """Hostile repository name and failure error message are sanitized and escaped."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        hostile_repo = '<script>alert("xss-repo")</script>'
        hostile_err = '<img src=x onerror=alert("xss-err")>'

        job = AnalysisJobModel(
            id=207,
            user_id=mock_user.id,
            repo_url=f"https://github.com/evil/{hostile_repo}",
            repo_name=hostile_repo,
            status="failed",
            error_message=hostile_err,
            created_at=datetime.now(timezone.utc),
        )
        html_out = progress_view(job, current_user=mock_user)

        assert '<script>alert("xss-repo")</script>' not in html_out
        assert '<img src=x' not in html_out
        assert 'onerror=alert' not in html_out
        assert '&lt;script&gt;alert' in html_out or '&quot;xss-repo&quot;' in html_out

    def test_required_ids_and_labels_present(self, mock_user, monkeypatch):
        """All required UI element IDs, 4 phase names, and 11 stage titles are present."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        job = AnalysisJobModel(
            id=208,
            user_id=mock_user.id,
            repo_url="https://github.com/torvalds/linux",
            repo_name="linux",
            status="running",
            created_at=datetime.now(timezone.utc),
        )
        html_out = progress_view(job, current_user=mock_user)

        required_ids = [
            "progress-stepper",
            "sse-terminal-log",
            "active-card",
            "active-sentence",
            "active-card-timer",
            "progress-bar-fill",
            "report-ready-card",
            "ready-files-count",
            "ready-modules-count",
            "ready-entry-count",
            "start-learning-btn",
            "failed-card",
            "failed-reason-text",
            "retry-btn",
            "cancelled-card",
            "cancel-form",
            "connection-lost-banner",
            "details-toggle",
        ]
        for rid in required_ids:
            assert f'id="{rid}"' in html_out, f"Required id '{rid}' missing from progress view"

        phase_names = [
            "Get the code",
            "Read the files",
            "Map how they connect",
            "Build your guide",
        ]
        for pname in phase_names:
            assert pname in html_out, f"Phase name '{pname}' missing from progress view"

        stage_titles = [
            "Consent & Auth Gate",
            "Shallow Clone",
            "Discovery & File Hierarchy",
            "Code Structure Parsing",
            "Global Symbol Table",
            "Directed Dependency Graph",
            "Architecture Domain Mapping",
            "Step-by-step narration",
            "Graph & Quiz Generation",
            "Persistence & Architecture Report Assembly",
            "Telemetry & Quota Allocation",
        ]
        for stitle in stage_titles:
            assert stitle in html_out, f"Stage title '{stitle}' missing from progress view"

    def test_dropped_elements_absent(self, mock_user, monkeypatch):
        """Dropped elements (durations, file counts on running cards, linking N of M, chip, disabled map) are absent."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        job = AnalysisJobModel(
            id=209,
            user_id=mock_user.id,
            repo_url="https://github.com/torvalds/linux",
            repo_name="linux",
            status="running",
            created_at=datetime.now(timezone.utc),
        )
        html_out = progress_view(job, current_user=mock_user)

        # 1. No per-step durations (e.g. 4.2s, 12.8s)
        assert not re.search(r'>\s*\d+\.\d+s\s*<', html_out), "Found per-step duration in progress view"

        # 2. No file counts on running cards
        assert "Downloaded the repo (" not in html_out
        assert "Read 96 files" not in html_out
        assert "(128 files)" not in html_out

        # 3. No 'Linking imports N of M'
        assert "Linking imports" not in html_out

        # 4. No current-file chip
        assert "current-file" not in html_out
        assert "current-file-chip" not in html_out

        # 5. No disabled 'View map' button
        assert not re.search(r'disabled[^>]*>View map<', html_out, re.IGNORECASE)
        assert not re.search(r'View map[^<]*disabled', html_out, re.IGNORECASE)


class TestFrontend2ProgressPlaywright:
    """Playwright browser tests on a live server at 390/768/1440 viewports with SSE events and cancel flow."""

    def test_progress_live_viewports_events_and_cancel(self, test_db, monkeypatch):
        """Verify responsive layouts, no horizontal scroll, healthy SSE stream, pushed events, and cancel confirm."""
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
                github_id=88099,
                github_username="pw_prog_user",
                email="pw_prog@example.com",
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            user_id = user.id

            job = AnalysisJobRepository.create_job(
                session=session,
                user_id=user_id,
                repo_url="https://github.com/expressjs/express",
                repo_name="express",
                status="running",
            )
            session.commit()
            job_id = job.id

        token = create_access_token(
            user_id=user_id,
            github_id=88099,
            github_username="pw_prog_user",
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

        os.makedirs(os.path.join("scratch", "f2_progress"), exist_ok=True)

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
                    page.goto(f"http://127.0.0.1:{port}/progress/{job_id}", wait_until="networkidle")

                    # 1. Assert no horizontal scroll: scrollWidth <= innerWidth
                    scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
                    inner_width = page.evaluate("() => window.innerWidth")
                    assert scroll_width <= inner_width, f"Horizontal scroll detected at width {width}: {scroll_width} > {inner_width}"

                    # 2. Assert no 'Connection lost' banner on a healthy stream
                    banner = page.locator("#connection-lost-banner")
                    assert not banner.is_visible(), f"Connection lost banner is visible at width {width}"

                    # 3. Assert 'Get the code' is shown
                    assert page.locator("text=Get the code").first.is_visible(), f"'Get the code' not visible at width {width}"

                    # 4. Save screenshot to scratch/f2_progress/
                    shot_path = os.path.join("scratch", "f2_progress", f"progress_{width}.png")
                    page.screenshot(path=shot_path, full_page=False)

                # 5. Pushed progress event updates active sentence and stepper
                page.set_viewport_size({"width": 768, "height": 844})
                page.evaluate(
                    """window._handleSSEData({
                        type: 'progress',
                        stage: 'stage_3',
                        stage_index: 4,
                        stage_total: 11,
                        message: 'Parsing concrete syntax trees and symbols…',
                        percentage: 35
                    });"""
                )
                time.sleep(0.1)

                active_sentence = page.locator("#active-sentence")
                assert "Parsing concrete syntax trees and symbols…" in active_sentence.text_content()
                assert "Step 2 of 4" in page.locator("#step-n-of-4-text").text_content()

                # 6. Pushed completed event displays #report-ready-card with the 3 real counts
                page.evaluate(
                    """window._handleSSEData({
                        type: 'completed',
                        job_id: '%s',
                        percentage: 100,
                        files_analyzed: 142,
                        modules_mapped: 8,
                        entry_points: 3
                    });""" % job_id
                )
                time.sleep(0.1)

                ready_card = page.locator("#report-ready-card")
                assert ready_card.is_visible()
                assert page.locator("#ready-files-count").text_content() == "142"
                assert page.locator("#ready-modules-count").text_content() == "8"
                assert page.locator("#ready-entry-count").text_content() == "3"
                assert not page.locator("#active-card").is_visible()

                completed_shot = os.path.join("scratch", "f2_progress", "progress_completed_768.png")
                page.screenshot(path=completed_shot, full_page=False)

                # 7. Cancel confirmation sheet opens and confirm button submits real POST /jobs/{id}/cancel
                with TestingSessionLocal() as s_cancel:
                    job_cancel = AnalysisJobRepository.create_job(
                        session=s_cancel,
                        user_id=user_id,
                        repo_url="https://github.com/expressjs/express-cancel",
                        repo_name="express-cancel",
                        status="running",
                    )
                    s_cancel.commit()
                    cancel_job_id = job_cancel.id

                page.route(
                    f"**/api/analyses/{cancel_job_id}/events",
                    lambda route: route.fulfill(
                        status=200,
                        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
                        body=": heartbeat\n\n",
                    ),
                )
                page.goto(f"http://127.0.0.1:{port}/progress/{cancel_job_id}", wait_until="networkidle")
                page.click("#open-cancel-btn")

                cancel_modal = page.locator("#cancel-modal")
                assert cancel_modal.is_visible()
                assert "open" in (cancel_modal.get_attribute("class") or "")

                cancel_form = page.locator("#cancel-form")
                assert cancel_form.get_attribute("action") == f"/jobs/{cancel_job_id}/cancel"
                assert cancel_form.get_attribute("method") == "POST"

                # Assert that clicking the confirm button submits the real POST request to /jobs/{cancel_job_id}/cancel
                with page.expect_request(lambda r: f"/jobs/{cancel_job_id}/cancel" in r.url and r.method == "POST") as req_info:
                    page.click("#cancel-btn")

                cancel_req = req_info.value
                assert cancel_req.method == "POST"
                assert f"/jobs/{cancel_job_id}/cancel" in cancel_req.url

                browser.close()
        finally:
            server.should_exit = True
            server_thread.join(timeout=3)
            app.dependency_overrides.clear()
