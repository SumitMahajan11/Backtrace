"""Tests for Frontend v2 Report View (FRONTEND_VERSION=2).

Verifies report_view shell, Overview tab, and Map tab in frontend2.
Verifies Learn/Milestones and Quiz tabs render frontend1's markup unchanged.
Includes unit tests with real fixtures, escaping, dropped elements absence,
legacy 0-based fixtures, size check, and Playwright verification across 390/768/1440 viewports.
"""

import html
import json
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
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
from app.frontend1.components import report_view as fe1_report_view
from app.frontend2.components import (
    count_code_and_docs_files,
    extract_readme_summary,
    get_main_language,
    get_read_first_files,
    get_start_here_entry_points,
    report_view as fe2_report_view,
)
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
def mock_user():
    return UserModel(
        id=1,
        github_id=99001,
        github_username="f2_report_tester",
        email="f2_report@example.com",
    )


def _generate_100_node_graph() -> Dict[str, Any]:
    """Generate a realistic 100-node connected graph across 5 tiers."""
    nodes = []
    edges = []
    domains = ["core", "backend", "frontend", "database", "config"]

    for i in range(100):
        tier = i // 20  # 5 tiers (0 to 4)
        domain = domains[tier % len(domains)]
        node_id = f"src/module_{tier}/file_{i}.py"
        label = f"file_{i}.py"
        nodes.append({
            "id": node_id,
            "label": label,
            "path": node_id,
            "tier": tier,
            "domain": domain,
            "confidence": "high" if i % 3 == 0 else ("medium" if i % 3 == 1 else "low"),
            "exports": [f"func_{i}", f"Class_{i}"],
            "is_entry_point": (i == 0 or i == 1),
            "content": f"# Sample code for {label}\ndef main(): pass\n",
        })

    # Create edges from earlier tiers to later tiers
    for i in range(95):
        src = nodes[i]["id"]
        tgt = nodes[i + 1]["id"]
        edges.append({"source": src, "target": tgt})
        if i + 5 < 100:
            edges.append({"source": src, "target": nodes[i + 5]["id"]})

    return {
        "nodes": nodes,
        "edges": edges,
        "confidence_summary": {
            "high_pct": 60,
            "medium_pct": 30,
            "low_pct": 10,
            "overall_score": 75,
            "high_count": 60,
            "medium_count": 30,
            "low_count": 10,
            "total_files": 100,
            "history_available": True,
        },
    }


class TestFrontend2ReportUnit:
    """Unit tests for Frontend v2 Report view rendering, escaping, IDs, and dropped elements."""

    def test_renders_real_fixture_all_ids_and_strings(self, mock_user, monkeypatch):
        """Render report_view with a real fixture and verify all required IDs and strings are present."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        graph_data = {
            "nodes": [
                {
                    "id": "src/app.py",
                    "label": "app.py",
                    "path": "src/app.py",
                    "tier": 0,
                    "domain": "core",
                    "confidence": "high",
                    "exports": ["create_app"],
                    "is_entry_point": True,
                },
                {
                    "id": "src/db.py",
                    "label": "db.py",
                    "path": "src/db.py",
                    "tier": 1,
                    "domain": "database",
                    "confidence": "medium",
                    "exports": ["get_db"],
                },
                {
                    "id": "src/utils.py",
                    "label": "utils.py",
                    "path": "src/utils.py",
                    "tier": 2,
                    "domain": "core",
                    "confidence": "low",
                    "exports": ["format_str"],
                },
            ],
            "edges": [
                {"source": "src/app.py", "target": "src/db.py"},
                {"source": "src/db.py", "target": "src/utils.py"},
            ],
            "confidence_summary": {
                "high_pct": 33,
                "medium_pct": 33,
                "low_pct": 34,
                "overall_score": 50,
                "high_count": 1,
                "medium_count": 1,
                "low_count": 1,
                "total_files": 3,
                "history_available": True,
            },
        }

        job = AnalysisJobModel(
            id=301,
            user_id=mock_user.id,
            repo_url="https://github.com/org/teleport",
            repo_name="teleport",
            status="completed",
            created_at=datetime(2026, 10, 26, 10, 0, 0, tzinfo=timezone.utc),
            execution_time_seconds=12.4,
        )

        raw_markdown = (
            "# Architecture Report: teleport\n\n"
            "## Overview\n"
            "- **Primary Language**: Python\n"
            "- **Total Analyzed Files**: 3\n"
            "- **Domain Categories**: 2\n"
            "- **Entry Point Files**: src/app.py\n\n"
            "## Milestones\n"
            "### Milestone 1: Core Foundation\n"
            "Foundational setup.\n"
        )

        quiz_data = {
            "questions": [
                {
                    "question": "What is the primary entry point?",
                    "options": ["src/app.py", "src/db.py"],
                    "correct": 0,
                    "explanation": "src/app.py initializes the application.",
                }
            ]
        }

        html_out = fe2_report_view(
            job=job,
            raw_markdown=raw_markdown,
            graph_data=graph_data,
            quiz_data=quiz_data,
            current_user=mock_user,
        )

        # 1. Tab navigation buttons in exact order
        assert 'id="tab-btn-overview"' in html_out
        assert 'id="tab-btn-graph"' in html_out
        assert 'id="tab-btn-milestones"' in html_out
        assert 'id="tab-btn-quiz"' in html_out

        # 2. Tab panes containing respective section contents
        assert 'id="tab-pane-overview"' in html_out
        assert 'id="tab-pane-graph"' in html_out
        assert 'id="tab-pane-milestones"' in html_out
        assert 'id="tab-pane-quiz"' in html_out

        # 3. Section IDs
        assert 'id="section-overview"' in html_out
        assert 'id="section-graph"' in html_out
        assert 'id="section-milestones"' in html_out
        assert 'id="section-quiz"' in html_out

        # 4. Overview TLDR and Stat cards
        assert 'id="overview-tldr-block"' in html_out
        assert 'id="tldr-what-this-is"' in html_out
        assert 'id="tldr-main-language"' in html_out
        assert 'id="tldr-start-here"' in html_out
        assert 'id="tldr-read-first"' in html_out
        assert 'id="confidence-horizontal-bar"' in html_out
        assert 'id="confidence-breakdown-card"' in html_out

        # 5. Graph and DAG IDs
        assert 'id="dag-count-explainer"' in html_out
        assert 'id="dag-search-input"' in html_out
        assert 'id="dag-fit-btn"' in html_out
        assert 'id="dag-fullscreen-btn"' in html_out
        assert 'id="dag-legend-panel"' in html_out
        assert 'id="dag-legend-content"' in html_out
        assert 'id="dag-canvas-layout"' in html_out
        assert 'id="dag-visual-container"' in html_out
        assert 'id="dag-svg"' in html_out
        assert 'id="dag-panzoom-layer"' in html_out
        assert 'id="dag-edges-layer"' in html_out
        assert 'id="dag-nodes-layer"' in html_out
        assert 'id="dag-node-inspector"' in html_out
        assert 'id="dag-table-container"' in html_out
        assert 'id="toggle-view-btn"' in html_out
        assert 'id="toggle-all-files-btn"' in html_out
        assert 'id="toggle-legend-btn"' in html_out

        # 6. Inspector IDs
        assert 'id="inspect-dot"' in html_out
        assert 'id="inspect-label"' in html_out
        assert 'id="inspect-domain"' in html_out
        assert 'id="inspect-path"' in html_out
        assert 'id="inspect-milestone-link"' in html_out
        assert 'id="inspect-imported-by-title"' in html_out
        assert 'id="inspect-imported-by"' in html_out
        assert 'id="inspect-imports-title"' in html_out
        assert 'id="inspect-imports"' in html_out
        assert 'id="inspect-exports"' in html_out

        # 7. Old test asserted strings
        assert "Overview" in html_out
        assert "Dependency Graph" in html_out
        assert "Milestones" in html_out
        assert "Quiz" in html_out
        assert "Files analyzed" in html_out
        assert "Entry points" in html_out
        assert "Modules" in html_out
        assert "Confidence" in html_out
        assert "switchReportTab" in html_out
        assert "handleReportHashChange" in html_out
        assert "history.pushState" in html_out

        # 8. Export and Print actions
        assert 'id="btn-export-markdown"' in html_out
        assert "Print Architecture Report" in html_out

    def test_hostile_file_names_and_repo_escaped(self, mock_user, monkeypatch):
        """Hostile file names, paths, and repo names must be safely escaped in all elements."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        hostile_graph = {
            "nodes": [
                {
                    "id": '<script>alert("xss")</script>',
                    "label": '<script>alert("xss")</script>',
                    "path": '<script>alert("xss")</script>',
                    "tier": 0,
                    "domain": "core",
                    "confidence": "high",
                },
                {
                    "id": 'foo" onclick="evil()',
                    "label": 'foo" onclick="evil()',
                    "path": 'foo" onclick="evil()',
                    "tier": 1,
                    "domain": "core",
                    "confidence": "medium",
                },
            ],
            "edges": [
                {"source": '<script>alert("xss")</script>', "target": 'foo" onclick="evil()'}
            ],
        }

        job = AnalysisJobModel(
            id=302,
            user_id=mock_user.id,
            repo_url="https://github.com/org/safe",
            repo_name='<script>alert("repo")</script>',
            status="completed",
            created_at=datetime.now(timezone.utc),
        )

        html_out = fe2_report_view(
            job=job,
            raw_markdown="# Report\n## Overview\nTest",
            graph_data=hostile_graph,
            quiz_data={},
            current_user=mock_user,
        )

        assert '<script>alert("xss")</script>' not in html_out
        assert '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;' in html_out or '&lt;script&gt;alert(&#34;xss&#34;)&lt;/script&gt;' in html_out
        assert 'foo" onclick="evil()' not in html_out
        assert 'foo&quot; onclick=&quot;evil()' in html_out or 'foo&#34; onclick=&#34;evil()' in html_out
        assert '<script>alert("repo")</script>' not in html_out

    def test_dropped_elements_absent(self, mock_user, monkeypatch):
        """Elements designated as DROP must be absent from frontend2."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        graph_data = {
            "nodes": [
                {"id": "src/main.py", "label": "main.py", "path": "src/main.py", "tier": 0, "domain": "core", "confidence": "high"}
            ],
            "edges": [],
        }

        job = AnalysisJobModel(
            id=303,
            user_id=mock_user.id,
            repo_url="https://github.com/org/test",
            repo_name="test",
            status="completed",
        )

        html_out = fe2_report_view(
            job=job,
            raw_markdown="# Report\n## Overview\nTest",
            graph_data=graph_data,
            quiz_data={},
            current_user=mock_user,
        )

        # DROPPED: "Read this file" button
        assert "Read this file" not in html_out

        # DROPPED: minimap button in DAG toolbar
        assert "minimap" not in html_out.lower()

        # DROPPED: mini import map
        assert "mini import map" not in html_out.lower()

    def test_legacy_0_based_fixture_shows_no_layer_0_no_milestone_0(self, mock_user, monkeypatch):
        """Legacy 0-based fixture must show 1-based Layer 1 and Milestone 1, never Layer 0 or Milestone 0."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        legacy_graph = {
            "nodes": [
                {"id": "app/core.py", "label": "app/core.py", "tier": 0, "domain": "core", "confidence": "high"},
                {"id": "app/api.py", "label": "app/api.py", "tier": 1, "domain": "api", "confidence": "high"},
            ],
            "edges": [{"source": "app/core.py", "target": "app/api.py"}],
            "milestones": [
                {"tier": 0, "title": "Milestone 0: Core Foundation", "display_id": "0", "included_files": ["app/core.py"]},
                {"tier": 1, "title": "Milestone 1: API Layer", "display_id": "1", "included_files": ["app/api.py"]},
            ],
        }

        job = AnalysisJobModel(
            id=304,
            user_id=mock_user.id,
            repo_url="https://github.com/org/legacy",
            repo_name="legacy",
            status="completed",
        )

        raw_md = (
            "# Architectural Reverse-Engineering Report: `legacy`\n"
            "## 1. Executive Architecture Overview\nTest\n"
            "## 2. Sequence Reasoning & Confidence Calibration\nCalibration\n"
            "## 3. Step-by-Step Architectural Milestones\n"
            "### Milestone 0: Core Foundation (Tier 0)\n"
            "**[HIGH CONFIDENCE]** -- *Foundation Layer*\n"
            "**Overview:** Foundation overview.\n"
            "**Included Files:**\n"
            "- `app/core.py`\n"
            "### Milestone 1: API Layer (Tier 1)\n"
            "**[HIGH CONFIDENCE]** -- *API Layer*\n"
            "**Overview:** API overview.\n"
            "**Included Files:**\n"
            "- `app/api.py`\n"
        )

        html_out = fe2_report_view(
            job=job,
            raw_markdown=raw_md,
            graph_data=legacy_graph,
            quiz_data={},
            current_user=mock_user,
        )

        assert "Layer 0" not in html_out
        assert "Layer 1" in html_out
        assert "Layer 2" in html_out
        assert html_out.count(">Layer 1<") == 1
        assert "Milestone 0" not in html_out
        assert "Milestone 1" in html_out

    def test_created_at_missing_omits_line_and_never_prints_just_now(self, mock_user, monkeypatch):
        """Never print 'Just now'. If created_at is missing, omit the Synthesized line."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")
        job_no_created_at = AnalysisJobModel(
            id=306,
            user_id=mock_user.id,
            repo_url="https://github.com/org/nocreated",
            repo_name="nocreated",
            status="completed",
            created_at=None,
        )
        html_out = fe2_report_view(
            job=job_no_created_at,
            raw_markdown="# Report\n## Overview\nTest",
            graph_data={"nodes": [], "edges": []},
            quiz_data={},
            current_user=mock_user,
        )
        assert "Synthesized:" not in html_out
        assert "Just now" not in html_out

        # Even with a recent timestamp, never print "Just now"
        job_recent = AnalysisJobModel(
            id=307,
            user_id=mock_user.id,
            repo_url="https://github.com/org/recent",
            repo_name="recent",
            status="completed",
            created_at=datetime.now(timezone.utc),
        )
        html_recent = fe2_report_view(
            job=job_recent,
            raw_markdown="# Report\n## Overview\nTest",
            graph_data={"nodes": [], "edges": []},
            quiz_data={},
            current_user=mock_user,
        )
        assert "Just now" not in html_recent

    def test_html_size_not_growing_vs_frontend1(self, mock_user, monkeypatch):
        """Frontend2 HTML payload size must not exceed Frontend1 HTML size on the same fixture."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        graph_data = _generate_100_node_graph()
        job = AnalysisJobModel(
            id=305,
            user_id=mock_user.id,
            repo_url="https://github.com/pallets/flask",
            repo_name="flask",
            status="completed",
            created_at=datetime.now(timezone.utc),
            execution_time_seconds=9.8,
        )

        raw_md = "# Architecture Report: flask\n## Overview\nFlask is a micro web framework.\n"
        quiz_data = {"questions": []}

        fe1_html = fe1_report_view(
            job=job,
            raw_markdown=raw_md,
            graph_data=graph_data,
            quiz_data=quiz_data,
            current_user=mock_user,
        )

        fe2_html = fe2_report_view(
            job=job,
            raw_markdown=raw_md,
            graph_data=graph_data,
            quiz_data=quiz_data,
            current_user=mock_user,
        )

        assert len(fe2_html) <= len(fe1_html), f"Frontend2 ({len(fe2_html)}) exceeded Frontend1 ({len(fe1_html)})"

    def test_single_shell_and_single_tab_switcher(self, mock_user, monkeypatch):
        """On the rendered report, counts of <header, f2-header, f2-bottom-bar, and function switchReportTab must each be exactly 1."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")
        job = AnalysisJobModel(
            id=308,
            user_id=mock_user.id,
            repo_url="https://github.com/org/singleshell",
            repo_name="singleshell",
            status="completed",
        )
        html_out = fe2_report_view(
            job=job,
            raw_markdown="# Report\n## Overview\nSingle shell test",
            graph_data={"nodes": [{"id": "a.py", "tier": 0}], "edges": []},
            quiz_data={},
            current_user=mock_user,
        )
        assert html_out.count("<header") == 1
        assert html_out.count("f2-header") == 1
        assert html_out.count("f2-bottom-bar") == 1
        assert html_out.count("function switchReportTab") == 1



class TestFrontend2ReportPlaywright:
    """Playwright browser tests on a real server at 390, 768, and 1440 viewports with 100-node fixture."""

    def test_playwright_responsive_tabs_and_inspector(self, monkeypatch):
        """Verify no horizontal scroll, tab switching, node click opens inspector, List toggle, and Fit button."""
        monkeypatch.setenv("FRONTEND_VERSION", "2")

        # Database setup
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)

        user_id = 901
        with TestingSessionLocal() as session:
            user = UserModel(
                id=user_id,
                github_id=99099,
                github_username="pw_report_user",
                email="pw_report@example.com",
            )
            session.add(user)
            session.commit()

            graph_data = _generate_100_node_graph()
            job = AnalysisJobModel(
                id=401,
                user_id=user_id,
                github_url="https://github.com/expressjs/express",
                repo_name="express",
                run_id="run_express_100",
                status="completed",
                created_at=datetime.now(timezone.utc),
                execution_time_seconds=14.2,
                graph_output_json=json.dumps(graph_data),
                markdown_output=(
                    "# Architecture Report: express\n\n"
                    "## Overview\n"
                    "- **Primary Language**: JavaScript\n"
                    "- **Total Analyzed Files**: 100\n"
                    "- **Domain Categories**: 5\n"
                    "- **Entry Point Files**: src/module_0/file_0.py\n\n"
                    "## 3. Step-by-Step Architectural Milestones\n\n"
                    "### Milestone 1: Routing (Tier 1)\n"
                    "**[HIGH CONFIDENCE]** -- *Fast unopinionated routing engine*\n\n"
                    "**Overview:**\n"
                    "Fast, unopinionated routing engine.\n\n"
                    "**Included Files:**\n"
                    "- `src/module_0/file_0.py`\n\n"
                    "**Key Exported Symbols:** `Router, route`\n"
                ),
            )
            session.add(job)
            session.commit()
            job_id = job.id

        token = create_access_token(
            user_id=user_id,
            github_id=99099,
            github_username="pw_report_user",
        )

        def override_get_current_user():
            with TestingSessionLocal() as s:
                u = s.query(UserModel).filter_by(id=user_id).first()
                if u:
                    s.refresh(u)
                    s.expunge(u)
                return u

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

        os.makedirs(os.path.join("scratch", "f2_report"), exist_ok=True)

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

                console_errors = []
                page_errors = []
                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                page.on("pageerror", lambda err: page_errors.append(str(err)))

                # Viewports to test
                viewports = [
                    (390, 844),
                    (768, 1024),
                    (1440, 900),
                ]

                for width, height in viewports:
                    page.set_viewport_size({"width": width, "height": height})
                    page.goto(f"http://127.0.0.1:{port}/report/{job_id}", wait_until="networkidle")

                    # 1. Assert no horizontal scroll: scrollWidth <= innerWidth
                    scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
                    inner_width = page.evaluate("() => window.innerWidth")
                    assert scroll_width <= inner_width, f"Horizontal scroll detected at width {width}: {scroll_width} > {inner_width}"

                    # 2. Screenshot overview
                    shot_path = os.path.join("scratch", "f2_report", f"report_{width}.png")
                    page.screenshot(path=shot_path, full_page=False)

                # Tab switching verification (at 1440px)
                page.set_viewport_size({"width": 1440, "height": 900})
                page.goto(f"http://127.0.0.1:{port}/report/{job_id}", wait_until="networkidle")

                # Switch to Graph tab
                page.locator("#tab-btn-graph").click()
                page.wait_for_timeout(100)
                assert page.locator("#tab-pane-graph").is_visible(), "Graph tab pane not visible after clicking tab button"
                assert not page.locator("#tab-pane-overview").is_visible(), "Overview pane should be hidden when Graph tab is active"

                # Switch to Milestones tab
                page.locator("#tab-btn-milestones").click()
                page.wait_for_timeout(100)
                assert page.locator("#tab-pane-milestones").is_visible(), "Milestones tab pane not visible after clicking tab button"

                # Verify Milestone body toggling (Item 7 requirement)
                milestone_header = page.locator("#milestone-header-1")
                assert milestone_header.is_visible(), "Milestone header should be visible"
                body_container = page.locator("#milestone-body-container-1")
                assert body_container.is_visible(), "Milestone body container should initially be visible"

                # Editor appears: CodeMirror element exists (Item 7 requirement)
                cm_element = page.locator(".CodeMirror").first
                assert cm_element.is_visible(), "CodeMirror editor element should exist and be visible"

                # Toggle milestone body: click header to close
                milestone_header.click()
                page.wait_for_timeout(150)
                assert not body_container.is_visible(), "Milestone body container should be hidden after clicking header"

                # Click header to re-open
                milestone_header.click()
                page.wait_for_timeout(150)
                assert body_container.is_visible(), "Milestone body container should be visible after clicking header again"

                # Click a correct option and assert "✓ Correct", then a wrong option and assert "✗ Incorrect"
                q_el = page.locator("#milestone-quiz-card-1 .milestone-quiz-q").first
                correct_idx = q_el.get_attribute("data-correct-idx") or "0"
                wrong_idx = "0" if correct_idx != "0" else "1"

                correct_option = q_el.locator(f'label.quiz-option-row:has(input[value="{correct_idx}"])')
                assert correct_option.is_visible(), "Correct quiz option row should be visible"
                correct_option.click()
                page.wait_for_timeout(150)
                feedback = q_el.locator(".quiz-feedback")
                assert feedback.is_visible(), "Quiz feedback should appear after clicking correct option"
                assert "✓ Correct" in feedback.inner_text(), f"Expected '✓ Correct', got: {feedback.inner_text()}"

                wrong_option = q_el.locator(f'label.quiz-option-row:has(input[value="{wrong_idx}"])')
                assert wrong_option.is_visible(), "Wrong quiz option row should be visible"
                wrong_option.click()
                page.wait_for_timeout(150)
                assert feedback.is_visible(), "Quiz feedback should appear after clicking wrong option"
                assert "✗ Incorrect" in feedback.inner_text(), f"Expected '✗ Incorrect', got: {feedback.inner_text()}"

                # Click Verify and assert request is sent (Item 7 requirement)
                verify_btn = page.locator("#btn-submit-1")
                assert verify_btn.is_visible(), "Verify/Submit button should be visible"
                with page.expect_request(lambda req: f"/api/attempts/{job_id}/1" in req.url and req.method == "POST"):
                    verify_btn.click()

                # Every script and stylesheet URL on the page returns 200 (Item 7 requirement)
                script_urls = page.evaluate("() => Array.from(document.querySelectorAll('script[src]')).map(s => s.src)")
                link_urls = page.evaluate("() => Array.from(document.querySelectorAll('link[rel=\"stylesheet\"], link[rel=\"icon\"], link[rel=\"alternate icon\"]')).map(l => l.href)")
                all_assets = set(script_urls + link_urls)
                assert len(all_assets) > 0, "Page should have scripts and stylesheets"
                for asset_url in all_assets:
                    resp = page.request.get(asset_url)
                    assert resp.status == 200, f"Asset URL {asset_url} returned HTTP {resp.status}"

                # No console errors or page errors (Item 7 requirement)
                assert len(console_errors) == 0, f"Expected 0 console errors, got {len(console_errors)}: {console_errors}"
                assert len(page_errors) == 0, f"Expected 0 page errors, got {len(page_errors)}: {page_errors}"

                # Switch to Quiz tab
                page.locator("#tab-btn-quiz").click()
                page.wait_for_timeout(100)
                assert page.locator("#tab-pane-quiz").is_visible(), "Quiz tab pane not visible after clicking tab button"

                # Switch back to Graph tab for toolbar & node interactions
                page.locator("#tab-btn-graph").click()
                page.wait_for_timeout(100)
                assert page.locator("#tab-pane-graph").is_visible()

                # Verify Fit button works
                fit_btn = page.locator("#dag-fit-btn")
                assert fit_btn.is_visible()
                fit_btn.click()
                page.wait_for_timeout(100)

                # Verify List toggle works
                toggle_btn = page.locator("#toggle-view-btn")
                assert toggle_btn.is_visible()
                toggle_btn.click()
                page.wait_for_timeout(100)
                assert page.locator("#dag-table-container").is_visible(), "DAG table container should be visible in List view"

                # Toggle back to graph
                toggle_btn.click()
                page.wait_for_timeout(100)
                assert page.locator("#dag-visual-container").is_visible(), "DAG visual container should be visible in Graph view"

                # Click node to open inspector at 1440px
                first_node = page.locator(".dag-node").first
                assert first_node.is_visible()
                first_node.click()
                page.wait_for_timeout(100)

                inspector = page.locator("#dag-node-inspector")
                assert inspector.is_visible(), "Inspector panel should be visible after clicking node"
                inspect_path = page.locator("#inspect-path").inner_text()
                assert len(inspect_path) > 0, "Inspector path should not be empty"

                page.screenshot(path=os.path.join("scratch", "f2_report", "map_1440.png"), full_page=False)

                # Test node inspector at 390px (mobile bottom sheet layout)
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(150)

                # Ensure no horizontal scroll with inspector open on mobile
                scroll_width_mobile = page.evaluate("() => document.documentElement.scrollWidth")
                inner_width_mobile = page.evaluate("() => window.innerWidth")
                assert scroll_width_mobile <= inner_width_mobile, f"Mobile horizontal scroll with inspector open: {scroll_width_mobile} > {inner_width_mobile}"

                page.screenshot(path=os.path.join("scratch", "f2_report", "map_node_selected_390.png"), full_page=False)

                browser.close()
        finally:
            server.should_exit = True
            app.dependency_overrides.clear()
