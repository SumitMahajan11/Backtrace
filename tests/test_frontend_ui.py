"""Comprehensive Frontend UI, SSE Progress, XSS Sanitization, and IDOR Defense Tests."""

import datetime
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, UserModel
from app.security.auth import create_access_token, oauth_state_store
from app.services.auth_service import AuthService
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.milestone_attempt_repository import MilestoneAttemptRepository
from app.storage.user_repository import UserRepository
from app.ui.sanitizer import sanitize_text, render_safe_markdown


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

    def _create(github_id: int, username: str, is_admin: bool = False) -> UserModel:
        with SessionLocal() as session:
            user = UserRepository.upsert_github_user(
                session=session,
                github_id=github_id,
                github_username=username,
                email=f"{username}@example.com",
                avatar_url=f"https://avatars.example.com/{username}",
            )
            if is_admin:
                user.is_admin = True
            session.commit()
            session.refresh(user)
            return user

    return _create


# =========================================================================
# 1. Unauthenticated Route Protection & Redirect Tests
# =========================================================================

def test_unauthenticated_page_access_redirects_to_login(client):
    """
    Acceptance Criteria: Every protected page (/dashboard, /progress/123, /report/123)
    must redirect unauthenticated visitors to /login.
    """
    # 1. Root redirect
    resp_root = client.get("/", follow_redirects=False)
    assert resp_root.status_code == 302
    assert resp_root.headers["location"] == "/login"

    # 2. Dashboard redirect
    resp_dash = client.get("/dashboard", follow_redirects=False)
    assert resp_dash.status_code == 302
    assert resp_dash.headers["location"] == "/login"

    # 3. Progress view redirect
    resp_prog = client.get("/progress/job-999", follow_redirects=False)
    assert resp_prog.status_code == 302
    assert resp_prog.headers["location"] == "/login"

    # 4. Report view redirect
    resp_rep = client.get("/report/job-999", follow_redirects=False)
    assert resp_rep.status_code == 302
    assert resp_rep.headers["location"] == "/login"

    # 5. Analysis submission without auth redirects to /login
    resp_sub = client.post("/analyses/submit", data={"repo_url": "https://github.com/fastapi/fastapi"}, follow_redirects=False)
    assert resp_sub.status_code == 302
    assert resp_sub.headers["location"] == "/login"


def test_unauthenticated_api_sse_returns_401(client):
    """
    Acceptance Criteria: API SSE endpoint returns 401 when accessed without credentials.
    """
    resp = client.get("/api/analyses/job-123/events")
    assert resp.status_code == 401
    assert "Authentication required" in resp.json()["detail"]


# =========================================================================
# 2. Login Page & Cookie-Based Session Issuance
# =========================================================================

def test_login_page_renders_github_oauth_button(client):
    """
    Acceptance Criteria: GET /login renders a clean, accessible page with a GitHub sign-in button.
    """
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Welcome to Backtrace" in resp.text
    assert "Sign in with GitHub" in resp.text
    assert "/auth/github/login" in resp.text


def test_oauth_callback_sets_httponly_cookies_and_redirects(client, test_db):
    """
    Acceptance Criteria: OAuth callback sets secure httpOnly cookies on session issuance.
    """
    SessionLocal, _ = test_db
    valid_state = oauth_state_store.generate_state()

    mock_profile = {
        "github_id": 445566,
        "github_username": "frontend_dev",
        "email": "dev@example.com",
        "avatar_url": "https://avatars.example.com/u/445566",
    }

    with patch.object(AuthService, "exchange_github_code_async", new=AsyncMock(return_value="gho_mock_code")), \
         patch.object(AuthService, "fetch_github_user_profile_async", new=AsyncMock(return_value=mock_profile)):

        # Simulate browser request with Accept: text/html
        resp = client.get(
            f"/auth/github/callback?code=valid_code&state={valid_state}",
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert resp.headers["location"] == "/dashboard"
        
        # Verify httpOnly cookies were set
        assert "access_token" in resp.cookies
        assert "refresh_token" in resp.cookies


# =========================================================================
# 3. Dashboard View & Quota Badge
# =========================================================================

def test_dashboard_view_free_and_paid_tier_indicators(client, create_user):
    """
    Acceptance Criteria: Dashboard shows current quota usage and plan badge.
    """
    user = create_user(github_id=1111, username="coder_bob")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    
    # Cookie-authenticated request to Dashboard
    client.cookies.set("access_token", token)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Root-Cause Analysis Ledger" in resp.text
    assert "FREE TIER" in resp.text
    assert "0 / 5" in resp.text
    assert "Reconstruct Repository History" in resp.text
    assert "coder_bob" in resp.text


# =========================================================================
# 4. Repo Submission & Quota Gating
# =========================================================================

def test_repo_submission_creates_job_and_redirects_to_progress(client, create_user, test_db):
    """
    Acceptance Criteria: Submitting a valid repo creates an AnalysisJob and redirects to progress.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=2222, username="alice_builder")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    resp = client.post(
        "/analyses/submit",
        data={"repo_url": "https://github.com/psf/requests"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/progress/")

    # Verify job in DB
    with SessionLocal() as session:
        jobs = AnalysisJobRepository.get_jobs_for_user(session, user.id)
        assert len(jobs) == 1
        assert jobs[0].repo_url == "https://github.com/psf/requests"
        assert jobs[0].status == "running"


# =========================================================================
# 5. Server-Sent Events (SSE) Live Progress Streaming
# =========================================================================

def test_sse_progress_stream_emits_stage_transitions(client, create_user, test_db):
    """
    Acceptance Criteria: GET /api/analyses/{id}/events streams SSE events
    reflecting real stage transitions from stage_0 to completion.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=3333, username="steve_pipeline")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/pallets/flask",
            status="running",
        )
        job_id = job.id

    # Connect to SSE endpoint
    response = client.get(f"/api/analyses/{job_id}/events")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    events = []
    for line in response.iter_lines():
        if line and line.startswith("data: "):
            payload = json.loads(line[6:])
            events.append(payload)

    assert len(events) > 0
    stage_names = [e.get("stage") for e in events if "stage" in e]
    assert "stage_0" in stage_names
    assert "stage_5" in stage_names
    assert "stage_10" in stage_names

    # Final event must be completed
    assert events[-1]["type"] == "completed"
    assert events[-1]["job_id"] == str(job_id)


# =========================================================================
# 6. Report View Rendering (Markdown, Graph, Quiz)
# =========================================================================

def test_report_view_renders_markdown_graph_and_quiz(client, create_user, test_db):
    """
    Acceptance Criteria: Report view renders Layer 8 Markdown, Dependency Graph, and Quiz.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=4444, username="grace_hopper")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/tiangolo/fastapi",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown="""# FastAPI Architecture Report

## Core Highlights
FastAPI provides high performance ASGI routing based on Starlette and Pydantic.

- Dependency Injection Engine
- Automated OpenAPI Docs
""",
            graph_data={
                "nodes": [
                    {"id": "fastapi.applications", "type": "module", "dependencies": ["fastapi.routing"]},
                    {"id": "fastapi.routing", "type": "module", "dependencies": ["fastapi.params"]},
                ],
                "edges": [{"from": "fastapi.applications", "to": "fastapi.routing"}],
            },
            quiz_data={
                "questions": [
                    {
                        "question": "Which component manages data validation in FastAPI?",
                        "options": ["Pydantic", "Jinja2", "SQLite"],
                        "answer": "Pydantic",
                    }
                ]
            },
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    assert "Codebase Intelligence Report" in resp.text
    assert "FastAPI Architecture Report" in resp.text
    assert "Architecture &amp; Dependency Graph" in resp.text
    assert "fastapi.applications" in resp.text
    assert "Codebase Mastery Quiz" in resp.text
    assert "Which component manages data validation in FastAPI?" in resp.text
    assert "Pydantic" in resp.text


# =========================================================================
# 7. Threat Model: XSS Sanitization Defense Test
# =========================================================================

def test_xss_payload_in_repo_content_renders_inert(client, create_user, test_db):
    """
    Acceptance Criteria (Threat Model):
    Malicious repository containing <script>alert(1)</script> or onerror attributes
    in filenames, markdown, or quiz questions must render completely inert (escaped).
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=5555, username="security_auditor")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    xss_script = "<script>alert('XSS_VULNERABILITY')</script>"
    xss_img = '<img src=x onerror=alert("XSS_IMG")>'
    xss_markdown = f"""# Malicious Repo Report

{xss_script}

{xss_img}

```javascript
console.log("{xss_script}");
```
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/evil-corp/xss-repo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=xss_markdown,
            graph_data={
                "nodes": [
                    {"id": f"malicious_module_{xss_script}", "type": "exploit", "dependencies": []}
                ],
                "edges": [],
            },
            quiz_data={
                "questions": [
                    {
                        "question": f"Exploit question: {xss_script}",
                        "options": [f"Option 1: {xss_img}", "Safe Option"],
                        "answer": "Safe Option",
                    }
                ]
            },
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    rendered_html = resp.text

    # Verify that raw executable script tags do NOT exist in the rendered output
    assert "<script>alert('XSS_VULNERABILITY')</script>" not in rendered_html
    assert '<img src=x onerror=alert("XSS_IMG")>' not in rendered_html

    # Verify that escaped safe entities exist instead
    assert "&lt;script&gt;alert(&#x27;XSS_VULNERABILITY&#x27;)&lt;/script&gt;" in rendered_html or "&lt;script&gt;" in rendered_html
    assert "&lt;img src=x" in rendered_html


def test_graph_dag_node_single_quote_xss_sink(client, create_user, test_db):
    """
    Threat Model: Graph node IDs containing single quotes (e.g. a');alert(1);//.py)
    must NOT produce raw/decoded inline handler breakout strings.
    Must use data-node-id and selectDagNode(this.dataset.nodeId), and truncate before escaping.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9911, username="graph_sec_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    single_quote_payload = "a');alert(1);//.py"
    long_entity_path = "/src/very/long/path/with/quotes/\"special\"/and/'single'/module_name.py"

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/evil-corp/graph-xss",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown="# Safe Graph Report",
            graph_data={
                "nodes": [
                    {
                        "id": single_quote_payload,
                        "label": single_quote_payload,
                        "path": long_entity_path,
                        "domain": "core",
                        "tier": 1,
                        "confidence": "high",
                    }
                ],
                "edges": [],
            },
            quiz_data={"questions": []},
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html = resp.text

    # 1. Ensure unsafe inline handler with single quote string interpolation is NOT present
    assert f"selectDagNode('{single_quote_payload}')" not in html
    assert "selectDagNode(&#x27;" not in html
    assert "hoverDagNode(&#x27;" not in html

    # 2. Ensure safe dataset invocation is used
    assert 'onclick="selectDagNode(this.dataset.nodeId)"' in html
    assert 'onmouseenter="hoverDagNode(this.dataset.nodeId)"' in html
    assert 'data-node-id="a&#x27;);alert(1);//.py"' in html

    # 3. Ensure truncation does not produce truncated entity fragments like 'ot;GRAPH'
    assert "ot;GRAPH" not in html
    assert "&#x27;single&#x27;/module_name.py" in html


def test_diff_ast_args_xss_sanitization():
    """Threat Model: Malicious repository functions with XSS in arguments are escaped in diff HTML."""
    from app.ui.components import _render_server_diff_html
    malicious_verification = {
        "structurally_verified": True,
        "present_symbols": [
            {
                "matched": {
                    "name": "exploit_fn",
                    "kind": "function",
                    "args": ["<script>alert(1)</script>", "valid_arg"],
                }
            }
        ],
    }
    rendered = _render_server_diff_html(malicious_verification)
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered


def test_progress_view_sse_log_safe_dom():
    """Threat Model: Progress view script constructs safe text nodes rather than using raw innerHTML on SSE text."""
    from app.ui.components import progress_view
    from unittest.mock import MagicMock
    mock_job = MagicMock()
    mock_job.id = 123
    mock_job.repo_url = "https://github.com/example/safe"
    mock_user = MagicMock()
    mock_user.github_username = "testuser"
    mock_user.avatar_url = ""

    html_out = progress_view(job=mock_job, current_user=mock_user)
    assert "msgSpan.textContent = text;" in html_out
    assert "line.innerHTML = `<span" not in html_out


# =========================================================================
# 8. Threat Model: IDOR (Insecure Direct Object Reference) Protection Test
# =========================================================================

def test_idor_cross_user_access_strictly_rejected(client, create_user, test_db):
    """
    Acceptance Criteria (Threat Model):
    User A's analysis job must NEVER be accessible by User B.
    Attempts by User B to access User A's progress, report, or SSE stream must return 403 Forbidden
    without leaking User A's repo name or analysis data.
    """
    SessionLocal, _ = test_db

    # Create User A (Owner)
    user_a = create_user(github_id=8801, username="user_a_owner")
    token_a = create_access_token(user_id=user_a.id, github_id=user_a.github_id, github_username=user_a.github_username)

    # Create User B (Attacker / Snooper)
    user_b = create_user(github_id=8802, username="user_b_attacker")
    token_b = create_access_token(user_id=user_b.id, github_id=user_b.github_id, github_username=user_b.github_username)

    # User A creates a confidential analysis job
    with SessionLocal() as session:
        job_a = AnalysisJobRepository.create_job(
            session=session,
            user_id=user_a.id,
            repo_url="https://github.com/secret-org/proprietary-core",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job_a.id,
            status="completed",
            report_markdown="# Confidential Intellectual Property",
            graph_data={"nodes": [{"id": "secret.module"}], "edges": []},
            quiz_data={"questions": []},
        )
        job_a_id = job_a.id

    # 1. User A can access their own report
    client.cookies.set("access_token", token_a)
    resp_owner = client.get(f"/report/{job_a_id}")
    assert resp_owner.status_code == 200
    assert "proprietary-core" in resp_owner.text

    # 2. User B tries to view User A's report -> MUST BE REJECTED WITH 403
    client.cookies.set("access_token", token_b)
    resp_attacker_report = client.get(f"/report/{job_a_id}")
    assert resp_attacker_report.status_code == 403
    assert "Access forbidden: You do not own this analysis job" in resp_attacker_report.json()["detail"]
    assert "proprietary-core" not in resp_attacker_report.text  # Zero info leakage

    # 3. User B tries to view User A's progress -> MUST BE REJECTED WITH 403
    resp_attacker_progress = client.get(f"/progress/{job_a_id}")
    assert resp_attacker_progress.status_code == 403
    assert "Access forbidden: You do not own this analysis job" in resp_attacker_progress.json()["detail"]
    assert "proprietary-core" not in resp_attacker_progress.text

    # 4. User B tries to subscribe to User A's SSE event stream -> MUST BE REJECTED WITH 403
    resp_attacker_sse = client.get(f"/api/analyses/{job_a_id}/events")
    assert resp_attacker_sse.status_code == 403
    assert "Access forbidden: You do not own this analysis job" in resp_attacker_sse.json()["detail"]
    assert "proprietary-core" not in resp_attacker_sse.text


def test_report_view_dependency_graph_fullscreen_toggle(client, create_user, test_db):
    """
    Verify Dependency Graph Maximize/Minimize fullscreen toggle button,
    Escape key listener, and fullscreen CSS rules.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9901, username="graph_viewer")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/expressjs/express",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown="# Express Architecture Report",
            graph_data={
                "nodes": [
                    {"id": "lib/express.js", "tier": 0, "type": "module"},
                    {"id": "lib/router/index.js", "tier": 1, "type": "module"},
                ],
                "edges": [{"from": "lib/express.js", "to": "lib/router/index.js"}],
            },
            quiz_data={"questions": []},
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html = resp.text

    # Maximize button is rendered next to Reset and Table Catalog
    assert 'id="dag-fullscreen-btn"' in html
    assert "Maximize" in html
    assert "⛶" in html
    assert "toggleGraphFullscreen()" in html

    # JavaScript toggle function & Escape listener
    assert "function toggleGraphFullscreen" in html
    assert "card.classList.toggle('graph-fullscreen')" in html
    assert "e.key === 'Escape'" in html
    assert "requestAnimationFrame" in html

    # Fullscreen CSS rules
    assert "#section-graph.graph-fullscreen" in html
    assert "position: fixed !important;" in html
    assert "inset: 0 !important;" in html
    assert "z-index: 9999 !important;" in html
    assert "background: var(--ink) !important;" in html


def test_report_view_tabbed_navigation_structure(client, create_user, test_db):
    """
    Verify client-side tabbed layout: 4 tabs (Overview, Dependency Graph,
    Milestones, Quiz), pane structure, hash change listener, history pushState,
    and CodeMirror refresh hook.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9902, username="tab_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/pallets/click",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown="""# Click Architecture Report
### Overview
Click is a Python package for creating beautiful command line interfaces.

### Milestone 0: Core Types
- Defines base parameter types.
""",
            graph_data={
                "nodes": [{"id": "click.core", "tier": 0, "type": "module"}],
                "edges": [],
            },
            quiz_data={
                "questions": [{"question": "What is Click?", "options": ["CLI library"], "answer": "CLI library"}]
            },
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html = resp.text

    # Tab navigation bar and buttons in exact specified order
    assert 'class="report-tabs-nav"' in html
    assert 'id="tab-btn-overview"' in html
    assert 'id="tab-btn-graph"' in html
    assert 'id="tab-btn-milestones"' in html
    assert 'id="tab-btn-quiz"' in html

    assert "Overview" in html
    assert "Dependency Graph" in html
    assert "Milestones" in html
    assert "Quiz" in html

    # Tab panes containing their respective section contents
    assert 'id="tab-pane-overview"' in html
    assert 'id="tab-pane-graph"' in html
    assert 'id="tab-pane-milestones"' in html
    assert 'id="tab-pane-quiz"' in html

    assert 'id="section-overview"' in html
    assert 'id="section-graph"' in html
    assert 'id="section-milestones"' in html
    assert 'id="section-quiz"' in html

    # Client-side hash routing & history pushState scripts
    assert "function switchReportTab(tabKey, updateHash = true)" in html
    assert "function handleReportHashChange()" in html
    assert "history.pushState(null, '', '#' + tabKey)" in html
    assert "window.addEventListener('popstate', handleReportHashChange)" in html
    assert "window.addEventListener('hashchange', handleReportHashChange)" in html
    assert "VALID_REPORT_TABS = ['overview', 'graph', 'milestones', 'quiz']" in html


def test_confidence_score_badge_tooltips_and_explanations(client, create_user, test_db):
    """
    Verify that report view renders confidence info icons (ⓘ) and tooltips
    explaining real Layer 6 Stage C sequence scoring logic on milestone cards and Overview KPI grid.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9903, username="confidence_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/expressjs/express",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown="""# Express Architecture Report
*Synthesized at: 2026-09-23T20:00:00Z*

## 1. Executive Architecture Overview
- **Primary Language**: `JavaScript`
- **Total Analyzed Files**: `2`
- **Domain Categories**: `2`
- **Entry Point Files**: `index.js`
- **Cyclic Core Components**: `0`
- **Isolated / Support Files**: `0`

### Domain Distribution
| Domain Category | File Count | Percentage |
| :--- | :--- | :--- |
| `core` | 2 | 100.0% |

## 2. Build Order & Confidence Scoring
**Confidence & Verification Calibration (2 Scored Files):**
- **Verified History & Hard Topology (100.0% High Confidence):** These files have clean acyclic dependencies.

## 3. Step-by-Step Architectural Milestones
### Milestone 0: Core Application Framework (Tier 0)
**[HIGH CONFIDENCE (High: 2)]** -- *Foundation Layer*
**Overview:** Base express application setup.
**Domain Composition:** 2 core files.
**Included Files (2):**
- `lib/express.js`
- `lib/application.js`
**Key Exported Symbols:** `createApplication, express`
""",
            graph_data={
                "nodes": [
                    {"id": "lib/express.js", "tier": 0, "type": "module", "confidence": "high"},
                    {"id": "lib/application.js", "tier": 0, "type": "module", "confidence": "high"},
                ],
                "edges": [{"from": "lib/express.js", "to": "lib/application.js"}],
            },
            quiz_data={"questions": []},
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html = resp.text

    # Tooltip and Info Icon CSS and Elements
    assert "class=\"tooltip-container\"" in html
    assert "class=\"info-icon-btn\"" in html
    assert "class=\"confidence-tooltip\"" in html
    assert "ⓘ" in html

    # Overview KPI Grid Confidence Card
    assert "CONFIDENCE SCORE" in html
    assert "HIGH" in html

    # Tooltip explanation text based on real backend calculation logic
    assert "Sequence Confidence" in html
    assert "Strict AST imports" in html
    assert "Domain heuristics" in html
    assert "Cyclic clusters" in html


def test_dependency_graph_legend_rendering(client, create_user, test_db):
    """
    Verify that the Dependency Graph renders a dynamic node tag and color legend
    with toggle controls and accurate plain-language descriptions.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9904, username="legend_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/fastapi/fastapi",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown="""# FastAPI Architecture Report
### Milestone 0: Core Setup
- Setup core routing.
""",
            graph_data={
                "nodes": [
                    {"id": "fastapi/routing.py", "tier": 0, "domain": "core", "confidence": "high"},
                    {"id": "tests/test_api.py", "tier": 1, "domain": "tests", "confidence": "medium"},
                    {"id": "database/models.py", "tier": 0, "domain": "database", "confidence": "high"},
                ],
                "edges": [{"source": "tests/test_api.py", "target": "fastapi/routing.py"}],
            },
            quiz_data={"questions": []},
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html = resp.text

    # Legend elements and toggle button
    assert 'id="dag-legend-panel"' in html
    assert 'id="toggle-legend-btn"' in html
    assert "Legend" in html
    assert "Node Domains:" in html

    # Dynamic domain tags present in the test graph
    assert "CORE" in html
    assert "core application code" in html
    assert "TESTS" in html
    assert "test files &amp; suites" in html
    assert "DATABASE" in html
    assert "database &amp; data models" in html

    # Confidence indicators
    assert "Confidence:" in html
    assert "High" in html
    assert "Medium" in html

    # Fullscreen compatibility rule
    assert "#section-graph.graph-fullscreen #dag-legend-panel" in html


def test_dependency_graph_full_path_node_tooltips(client, create_user, test_db):
    """
    Verify that nodes with long file paths retain their visual truncation while
    exposing the complete, untruncated path via native title attributes and SVG title elements.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9905, username="tooltip_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    long_path = "services/backend/deeply/nested/components/authentication/oauth_handler.py"
    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/org/repo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown="# Report",
            graph_data={
                "nodes": [
                    {
                        "id": long_path,
                        "path": long_path,
                        "label": "oauth_handler.py",
                        "tier": 0,
                        "domain": "backend",
                        "confidence": "high",
                    }
                ],
                "edges": [],
            },
            quiz_data={"questions": []},
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html = resp.text

    # The full path should be in the title attribute and SVG title element
    assert f'title="{long_path}"' in html
    assert f'<title>{long_path}</title>' in html

    # The visual truncated path should be the trailing 28 chars
    truncated_suffix = long_path[-28:]
    assert truncated_suffix in html

    # Verify click and hover interaction bindings are preserved
    assert f'data-node-id="{long_path}"' in html
    assert 'onclick="selectDagNode(this.dataset.nodeId)"' in html
    assert 'onmouseenter="hoverDagNode(this.dataset.nodeId)"' in html
    assert 'onmouseleave="unhoverDagNode()"' in html


def test_failed_job_error_message_surfaced_on_dashboard_and_progress(client, create_user, test_db):
    """
    Verify that when an analysis job fails, its error_message is prominently
    rendered on both the dashboard history ledger and the progress page.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9906, username="failure_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    failure_reason = "Repository file count exceeds maximum allowed cap of 150 files for v1."
    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/large/repo",
            status="failed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="failed",
            error_message=failure_reason,
        )
        job_id = job.id

    # 1. Check Dashboard View
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    dash_html = resp_dash.text

    assert "FAILED" in dash_html
    assert "job-failure-reason" in dash_html
    assert failure_reason in dash_html
    assert f'title="{failure_reason}"' in dash_html
    assert "Retry Analysis Job" in dash_html

    # 2. Check Progress View
    resp_prog = client.get(f"/progress/{job_id}")
    assert resp_prog.status_code == 200
    prog_html = resp_prog.text

    assert 'id="pipeline-failure-banner"' in prog_html
    assert "Analysis Execution Encountered a Fatal Error" in prog_html
    assert 'id="failure-error-message"' in prog_html
    assert failure_reason in prog_html
    assert "Retry Analysis Job" in prog_html


def test_execution_time_seconds_persisted_and_displayed_in_dashboard(client, create_user, test_db):
    """
    Verify that update_job_status records execution_time_seconds properly
    and the dashboard ledger renders formatted duration for completed/failed jobs
    while old 0.0 jobs display '—'.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9907, username="duration_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with SessionLocal() as session:
        # Job 1: Completed with 14.25 seconds
        job_comp = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/completed-repo",
            status="pending",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job_comp.id,
            status="completed",
            report_markdown="# Report",
            execution_time_seconds=14.25,
        )

        # Job 2: Failed with 4.8 seconds
        job_fail = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/failed-repo",
            status="pending",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job_fail.id,
            status="failed",
            error_message="SyntaxError in ast_parser",
            execution_time_seconds=4.8,
        )

        # Job 3: Old job with 0.0 seconds
        job_old = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/old-repo",
            status="completed",
        )

        job_comp_id = job_comp.id
        job_fail_id = job_fail.id

    # Query DB to verify persistence
    with SessionLocal() as session:
        j1 = AnalysisJobRepository.get_job_by_id(session, job_comp_id)
        assert j1.execution_time_seconds == 14.25
        j2 = AnalysisJobRepository.get_job_by_id(session, job_fail_id)
        assert j2.execution_time_seconds == 4.8

    # Query Dashboard to verify duration rendering in the table
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    dash_html = resp_dash.text

    assert "14.2s" in dash_html or "14.3s" in dash_html
    assert "4.8s" in dash_html
    assert "—" in dash_html


def test_progress_view_live_elapsed_timer(client, create_user, test_db):
    """
    Verify that the progress page renders the elapsed-time badge,
    initial timer label, and JavaScript ticker handlers.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9908, username="timer_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    # 1. Running job via /progress/{job_id} route
    with SessionLocal() as session:
        job_running = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/running-repo",
            status="running",
        )
        job_running_id = job_running.id

    resp_run = client.get(f"/progress/{job_running_id}")
    assert resp_run.status_code == 200
    run_html = resp_run.text

    assert 'id="elapsed-timer-badge"' in run_html
    assert 'id="elapsed-timer-text"' in run_html
    assert "Running for" in run_html
    assert "updateElapsedTimer" in run_html
    assert "setInterval(updateElapsedTimer, 1000)" in run_html

    # 2. Failed job with execution time via /progress/{job_id}
    with SessionLocal() as session:
        job_failed = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/failed-timer-repo",
            status="pending",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job_failed.id,
            status="failed",
            error_message="Fatal pipeline crash",
            execution_time_seconds=35.0,
        )
        job_failed_id = job_failed.id

    resp_fail = client.get(f"/progress/{job_failed_id}")
    assert resp_fail.status_code == 200
    fail_html = resp_fail.text

    assert 'id="elapsed-timer-badge"' in fail_html
    assert "Failed after 0:35" in fail_html

    # 3. Direct progress_view render for completed job
    with SessionLocal() as session:
        job_completed = AnalysisJobRepository.get_job_by_id(session, job_failed_id)
        job_completed.status = "completed"
        job_completed.execution_time_seconds = 82.0
        from app.ui.components import progress_view
        comp_html = progress_view(job=job_completed, current_user=user)

    assert 'id="elapsed-timer-badge"' in comp_html
    assert "Completed in 1:22" in comp_html


def test_dashboard_and_report_timestamps_include_seconds_for_same_minute_jobs(client, create_user, test_db):
    """
    Verify that jobs created in the same minute display distinct timestamps with seconds
    (%Y-%m-%d %H:%M:%S UTC) on the dashboard and report view.
    """
    import datetime
    SessionLocal, _ = test_db
    user = create_user(github_id=9909, username="timestamp_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    t1 = datetime.datetime(2026, 9, 23, 10, 15, 12, tzinfo=datetime.timezone.utc)
    t2 = datetime.datetime(2026, 9, 23, 10, 15, 48, tzinfo=datetime.timezone.utc)

    with SessionLocal() as session:
        job1 = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/repo-first",
            status="completed",
        )
        job1.created_at = t1

        job2 = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/repo-second",
            status="completed",
        )
        job2.created_at = t2
        session.commit()

        job1_id = job1.id
        job2_id = job2.id

    # 1. Dashboard View
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    dash_html = resp_dash.text

    assert "2026-09-23 10:15:12 UTC" in dash_html
    assert "2026-09-23 10:15:48 UTC" in dash_html

    # 2. Report View
    resp_report = client.get(f"/report/{job1_id}")
    assert resp_report.status_code == 200
    report_html = resp_report.text

    assert "SYNTHESIZED: 2026-09-23 10:15:12 UTC" in report_html


# =========================================================================
# 19. Milestone Engagement Mode Switcher & "Just Read It" Mode Tests
# =========================================================================

def test_milestone_mode_switcher_renders_options(client, create_user, test_db):
    """
    Acceptance Criteria:
    - Each milestone card has a visible 3-option mode switcher:
      'Guess It', 'Fill the Blanks', 'Just Read It'.
    - 'Guess It' is active by default.
    - 'Fill the Blanks' renders disabled with 'Soon' badge.
    - 'Just Read It' is an interactive option.
    - Existing Guess It code editor surface is preserved.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9871, username="mode_switcher_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    report_md = """# Architectural Reverse-Engineering Report: `test-repo`
*Synthesized at: 2026-09-23 10:15:12 UTC*

## 3. Step-by-Step Architectural Milestones

### Milestone 0: Foundation Layer
**[HIGH CONFIDENCE]** -- *Core database connectors*
**Overview:** Initializes base configuration.
**Domain Composition:** 100% Core
**Included Files:**
- `app/db.py`
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/mode-switcher-repo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={"nodes": [{"id": "app/db.py", "path": "app/db.py", "tier": 0}], "edges": []},
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html_text = resp.text

    # Mode switcher tab buttons
    assert 'id="mode-btn-guess-0"' in html_text
    assert 'id="mode-btn-fill-0"' in html_text
    assert 'id="mode-btn-read-0"' in html_text
    assert "Guess It" in html_text
    assert "Fill the Blanks" in html_text
    assert "Just Read It" in html_text

    # Fill the Blanks is disabled
    assert 'id="mode-btn-fill-0" class="milestone-mode-tab-btn disabled" disabled' in html_text

    # Workspaces
    assert 'id="workspace-guess-0"' in html_text
    assert 'id="workspace-read-0"' in html_text

    # Existing code editor preserved
    assert 'id="code-editor-0"' in html_text
    assert 'id="btn-run-0"' in html_text
    assert 'id="btn-submit-0"' in html_text


def test_just_read_it_mode_renders_real_file_content_and_file_picker(client, create_user, test_db):
    """
    Acceptance Criteria:
    - 'Just Read It' workspace contains the explanatory copy:
      'Read through this milestone\'s actual implementation'.
    - For multi-file milestones, renders a working file picker (tabs/buttons) defaulting to first file.
    - Displays real syntax-highlighted / read-only content of target files from IngestionResultModel.
    - Renders 'Mark as Reviewed' button.
    """
    from app.models.db import RepoModel, IngestionResultModel

    SessionLocal, _ = test_db
    user = create_user(github_id=9872, username="reader_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    repo_url = "https://github.com/test/multi-file-repo"
    file_contents_map = {
        "reelclaim-backend/app/db.py": "def get_db_session():\n    return 'connected'",
        "reelclaim-backend/app/config.py": "DATABASE_URL = 'sqlite:///app.db'\nDEBUG = True",
    }

    report_md = """# Architectural Reverse-Engineering Report: `multi-file-repo`
*Synthesized at: 2026-09-23 10:15:12 UTC*

## 3. Step-by-Step Architectural Milestones

### Milestone 0: Core Infrastructure
**[HIGH CONFIDENCE]** -- *Foundation database & settings*
**Overview:** Sets up database and configuration.
**Domain Composition:** 100% Core
**Included Files:**
- `reelclaim-backend/app/db.py`
- `reelclaim-backend/app/config.py`
"""

    with SessionLocal() as session:
        # Create RepoModel and IngestionResultModel with real file contents
        repo = RepoModel(
            github_url=repo_url,
            commit_hash="c0ffee123456",
            status="complete",
            expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
        )
        session.add(repo)
        session.flush()

        ingestion = IngestionResultModel(
            repo_id=repo.id,
            file_tree_json=json.dumps(["reelclaim-backend/app/db.py", "reelclaim-backend/app/config.py"]),
            file_contents_json=json.dumps(file_contents_map),
            skipped_files_json="[]",
        )
        session.add(ingestion)
        session.commit()

        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url=repo_url,
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={
                "nodes": [
                    {"id": "reelclaim-backend/app/db.py", "path": "reelclaim-backend/app/db.py", "tier": 0},
                    {"id": "reelclaim-backend/app/config.py", "path": "reelclaim-backend/app/config.py", "tier": 0},
                ],
                "edges": [],
            },
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html_text = resp.text

    # Explanatory text
    assert "Read through this milestone&#039;s actual implementation" in html_text or "Read through this milestone's actual implementation" in html_text

    # Multi-file file-picker tabs rendered
    assert 'id="read-file-tabs-0"' in html_text
    assert 'id="read-tab-btn-0-0"' in html_text
    assert 'id="read-tab-btn-0-1"' in html_text
    assert "db.py" in html_text
    assert "config.py" in html_text

    # Read-only file panes containing real file contents
    assert 'id="read-file-pane-0-0"' in html_text
    assert 'id="read-file-pane-0-1"' in html_text
    assert "def get_db_session():" in html_text
    assert "sqlite:///app.db" in html_text
    assert "DATABASE_URL" in html_text

    # Mark as Reviewed button rendered
    assert 'id="btn-review-0"' in html_text
    assert "Mark as Reviewed" in html_text


def test_mark_milestone_reviewed_endpoint_and_state_progression(client, create_user, test_db):
    """
    Acceptance Criteria:
    - POST /api/attempts/{job_id}/{milestone_tier}/review updates attempt status to 'structurally_verified'.
    - grading_method is set to 'reviewed'.
    - Marks milestone as complete without AST grading or score calculation.
    - IDOR check: Users cannot mark reviews for other users' jobs.
    - Subsequent report page render reflects verified completion status.
    """
    SessionLocal, _ = test_db
    user_owner = create_user(github_id=9873, username="review_owner")
    user_attacker = create_user(github_id=9874, username="review_attacker")

    token_owner = create_access_token(user_id=user_owner.id, github_id=user_owner.github_id, github_username=user_owner.github_username)
    token_attacker = create_access_token(user_id=user_attacker.id, github_id=user_attacker.github_id, github_username=user_attacker.github_username)

    report_md = """# Architectural Reverse-Engineering Report: `review-repo`
*Synthesized at: 2026-09-23 10:15:12 UTC*

## 3. Step-by-Step Architectural Milestones

### Milestone 0: Leaf Store
**[HIGH CONFIDENCE]** -- *Storage*
**Overview:** Storage adapter.
**Domain Composition:** 100% Core
**Included Files:**
- `app/storage.py`
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user_owner.id,
            repo_url="https://github.com/test/review-repo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={"nodes": [{"id": "app/storage.py", "path": "app/storage.py", "tier": 0}], "edges": []},
        )
        job_id = job.id

    # 1. IDOR Defense: Attacker cannot review owner's job
    client.cookies.set("access_token", token_attacker)
    resp_attack = client.post(f"/api/attempts/{job_id}/0/review")
    assert resp_attack.status_code == 403
    assert "Access forbidden" in resp_attack.json()["detail"]

    # 2. Owner marks milestone as reviewed
    client.cookies.set("access_token", token_owner)
    resp_review = client.post(f"/api/attempts/{job_id}/0/review")
    assert resp_review.status_code == 200
    data = resp_review.json()

    assert data["status"] == "structurally_verified"
    assert data["grading_method"] == "reviewed"
    assert data["attempt"]["milestone_tier"] == 0
    assert data["attempt"]["status"] == "structurally_verified"

    # 3. Verify in DB
    with SessionLocal() as session:
        attempt = MilestoneAttemptRepository.get_attempt(session, user_owner.id, job_id, 0)
        assert attempt is not None
        assert attempt.status == "structurally_verified"
        assert attempt.grading_method == "reviewed"

    # 4. Report View shows verified status and Reviewed & Verified label
    resp_report = client.get(f"/report/{job_id}")
    assert resp_report.status_code == 200
    report_html = resp_report.text

    assert 'STRUCTURALLY VERIFIED' in report_html
    assert 'Reviewed &amp; Verified ✓' in report_html or 'Reviewed & Verified ✓' in report_html


def test_guess_it_instructions_and_multi_file_tabs(client, create_user, test_db):
    """
    Acceptance Criteria:
    - Above the code editor, shows clear task instructions pulling milestone role/description:
      e.g. 'Try to reconstruct [filename] based on the expected symbols and this milestone's role in the codebase...'
    - Multi-file milestones render a file-picker tab control in 'Guess It' mode.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9875, username="guess_instructions_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    report_md = """# Architectural Reverse-Engineering Report: `multi-guess-repo`
*Synthesized at: 2026-09-23 10:15:12 UTC*

## 3. Step-by-Step Architectural Milestones

### Milestone 0: Core Architecture
**[HIGH CONFIDENCE]** -- *Foundational Primitives & Database Models*
**Overview:** Sets up database layer.
**Domain Composition:** 100% Core
**Included Files:**
- `app/db.py`
- `app/models.py`
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/multi-guess-repo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={"nodes": [{"id": "app/db.py", "path": "app/db.py", "tier": 0}, {"id": "app/models.py", "path": "app/models.py", "tier": 0}], "edges": []},
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html_text = resp.text

    # 1. Instructions banner with task objective, target filename, and milestone role
    assert "Task Instructions:" in html_text
    assert "Try to reconstruct" in html_text
    assert "id=\"guess-target-filename-0\"" in html_text
    assert "app/db.py" in html_text
    assert "Foundational Primitives &amp; Database Models" in html_text or "Foundational Primitives & Database Models" in html_text

    # 2. Multi-file tabs in Guess It workspace
    assert "id=\"guess-file-tabs-0\"" in html_text
    assert "id=\"guess-tab-btn-0-0\"" in html_text
    assert "id=\"guess-tab-btn-0-1\"" in html_text
    assert "db.py" in html_text
    assert "models.py" in html_text


def test_run_code_executes_successfully_and_returns_real_results(client, create_user, test_db):
    """
    Acceptance Criteria:
    - 'Run Code' executes the user's submitted code and returns real stdout/stderr/exit code.
    - Does not throw 'temporarily unavailable' 503 error.
    - Persists execution state in MilestoneAttempt record.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9876, username="run_code_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/run-code-repo",
            status="completed",
        )
        job_id = job.id

    client.cookies.set("access_token", token)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Valid code submission
    payload_valid = {
        "submitted_code": "def solve():\n    return 42\nprint('Output test:', solve())",
        "language": "python",
    }
    resp = client.post(f"/api/attempts/{job_id}/0/run", json=payload_valid, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["execution"]["exit_code"] == 0
    assert "Output test: 42" in data["execution"]["stdout"]
    assert data["execution"]["execution_time_ms"] >= 0
    assert data["attempt"]["last_run_stdout"] == data["execution"]["stdout"]

    # 2. Runtime error execution
    payload_err = {
        "submitted_code": "def crash():\n    1 / 0\ncrash()",
        "language": "python",
    }
    resp_err = client.post(f"/api/attempts/{job_id}/0/run", json=payload_err, headers=headers)
    assert resp_err.status_code == 200
    data_err = resp_err.json()

    assert data_err["execution"]["exit_code"] != 0
    assert "ZeroDivisionError" in data_err["execution"]["stderr"]


def test_guess_it_full_workspace_wiring_and_draft_persistence(client, create_user, test_db):
    """
    Acceptance Criteria:
    - Every milestone's 'Guess It' mode shows clear task instructions before any code is written.
    - Multi-file milestones render a file-picker with per-file draft persistence hooks.
    - 'Guess It' is a first-class selectable option in the mode switcher.
    - Mode switching between 'Guess It' and 'Just Read It' works seamlessly.
    - Submit Verification and hint-locked-behind-first-attempt flow is preserved.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9877, username="guess_workspace_pro")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    report_md = """# Architectural Reverse-Engineering Report: `guess-workspace-repo`
*Synthesized at: 2026-09-23 10:15:12 UTC*

## 3. Step-by-Step Architectural Milestones

### Milestone 0: Core Architecture
**[HIGH CONFIDENCE]** -- *Foundational Primitives & Zero-Dependency Leaf Utilities*
**Overview:** Initializes base primitive utilities.
**Domain Composition:** 100% Core
**Included Files:**
- `app/primitives.py`
- `app/constants.py`
- `app/helpers.py`
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/guess-workspace-repo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={
                "nodes": [
                    {"id": "app/primitives.py", "path": "app/primitives.py", "tier": 0, "name": "app/primitives.py"},
                    {"id": "app/constants.py", "path": "app/constants.py", "tier": 0, "name": "app/constants.py"},
                    {"id": "app/helpers.py", "path": "app/helpers.py", "tier": 0, "name": "app/helpers.py"},
                ],
                "edges": [],
            },
        )
        job_id = job.id

    # 1. Verify UI Rendering of Instructions, Tabs, and Mode Switcher
    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html_text = resp.text

    # Mode Switcher
    assert 'id="mode-btn-guess-0"' in html_text
    assert 'id="mode-btn-read-0"' in html_text
    assert 'switchMilestoneMode(0, \'guess\')' in html_text or "switchMilestoneMode(0, 'guess')" in html_text
    assert 'switchMilestoneMode(0, \'read\')' in html_text or "switchMilestoneMode(0, 'read')" in html_text

    # Task Instructions Banner
    assert "Task Instructions:" in html_text
    assert "Try to reconstruct" in html_text
    assert 'id="guess-target-filename-0"' in html_text
    assert "app/primitives.py" in html_text
    assert "Foundational Primitives &amp; Zero-Dependency Leaf Utilities" in html_text or "Foundational Primitives & Zero-Dependency Leaf Utilities" in html_text

    # Multi-file tabs
    assert 'id="guess-file-tabs-0"' in html_text
    assert 'id="guess-tab-btn-0-0"' in html_text
    assert 'id="guess-tab-btn-0-1"' in html_text
    assert 'id="guess-tab-btn-0-2"' in html_text
    assert "primitives.py" in html_text
    assert "constants.py" in html_text
    assert "helpers.py" in html_text

    # JavaScript Draft Isolation & Mode Switching Functions
    assert "window.guessFileDrafts" in html_text
    assert "window.activeGuessFileIdx" in html_text
    assert "function switchMilestoneGuessFile" in html_text
    assert "function switchMilestoneMode" in html_text
    assert "function runMilestoneCode" in html_text
    assert "function submitMilestoneCode" in html_text

    # Hint Locked Notice initially present before first attempt
    assert 'id="hint-locked-notice-0"' in html_text
    assert "Submit first attempt to unlock hints" in html_text

    # 2. Run Code endpoint executes without error
    headers = {"Authorization": f"Bearer {token}"}
    run_resp = client.post(
        f"/api/attempts/{job_id}/0/run",
        headers=headers,
        json={"submitted_code": "print('Reconstructed primitives')", "language": "python"},
    )
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["execution"]["exit_code"] == 0
    assert "Reconstructed primitives" in run_data["execution"]["stdout"]

    # 3. Submit Verification endpoint works and records attempt
    submit_resp = client.post(
        f"/api/attempts/{job_id}/0",
        headers=headers,
        json={"submitted_code": "def primitive(): pass"},
    )
    assert submit_resp.status_code == 200
    submit_data = submit_resp.json()
    assert "verification" in submit_data
    assert "attempt" in submit_data


def test_fill_the_blanks_ui_rendering_and_mode_switching(client, create_user, test_db):
    """
    Acceptance Criteria for Fill the Blanks:
    - Mode switcher correctly offers all three modes per milestone.
    - Milestone with scaffoldable functions has 'Fill the Blanks' enabled.
    - Milestone with only constants/types disables 'Fill the Blanks' with clear note.
    - 'Fill the Blanks' workspace preloads scaffolded code, instructions, chips, and immediate hints.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9878, username="fill_ui_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    math_source = """def calculate_total(prices, tax_rate=0.05):
    \"\"\"Calculate total price with tax.\"\"\"
    subtotal = sum(prices)
    return subtotal * (1 + tax_rate)
"""
    constants_source = """API_KEY = "SECRET_123"
MAX_RETRIES = 5
"""

    report_md = """# Architectural Reverse-Engineering Report: `fill-mode-repo`
*Synthesized at: 2026-09-23 10:15:12 UTC*

## 3. Step-by-Step Architectural Milestones

### Milestone 0: Math Operations
**[HIGH CONFIDENCE]** -- *Core Computation Utilities*
**Overview:** Arithmetic calculation helpers.
**Domain Composition:** 100% Core
**Included Files:**
- `app/math_ops.py`

### Milestone 1: Shared Constants
**[HIGH CONFIDENCE]** -- *Shared Config & Types*
**Overview:** System constants.
**Domain Composition:** 100% Core
**Included Files:**
- `app/constants.py`
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/fill-mode-repo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={
                "nodes": [
                    {"id": "app/math_ops.py", "path": "app/math_ops.py", "tier": 0, "source_code": math_source},
                    {"id": "app/constants.py", "path": "app/constants.py", "tier": 1, "source_code": constants_source},
                ],
                "edges": [],
            },
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html_text = resp.text

    # 1. Milestone 0 has active 'Fill the Blanks' mode button
    assert 'id="mode-btn-fill-0"' in html_text
    assert 'switchMilestoneMode(0, \'fill\')' in html_text or "switchMilestoneMode(0, 'fill')" in html_text
    assert 'class="milestone-mode-tab-btn disabled"' not in html_text.split('id="mode-btn-fill-0"')[0].split('<button')[-1]

    # 2. Milestone 1 (constants only) has disabled 'Fill the Blanks' mode button with explanatory tooltip
    assert 'id="mode-btn-fill-1"' in html_text
    assert 'No Blanks' in html_text
    assert 'File contains only constants, type declarations, or exports' in html_text

    # 3. Milestone 0 Fill the Blanks Workspace structure
    assert 'id="workspace-fill-0"' in html_text
    assert 'Fill the Blanks Instructions:' in html_text
    assert 'id="fill-target-filename-0"' in html_text
    assert 'math_ops.py' in html_text
    assert 'calculate_total' in html_text
    assert 'id="fill-blanked-chips-0"' in html_text
    assert 'id="code-editor-fill-0"' in html_text
    assert 'Calculate total price with tax.' in html_text  # Docstring preserved in scaffold

    # 4. Immediate Hints button present in Fill mode
    assert 'id="btn-hint-fill-0"' in html_text
    assert 'Request Architectural Hint' in html_text
    assert 'Hints unlocked' in html_text

    # 5. JavaScript functions for Fill mode present
    assert 'window.fillFilesData' in html_text
    assert 'window.fillFileDrafts' in html_text
    assert 'function switchMilestoneFillFile' in html_text
    assert 'function runMilestoneFillCode' in html_text
    assert 'function submitMilestoneFillCode' in html_text


def test_fill_the_blanks_disabled_for_non_python_files_shows_clear_tooltip(client, create_user, test_db):
    """Verifies that non-Python files (e.g. Go, Rust, Java, TS) render a disabled Fill the Blanks tab
    with a clear tooltip stating that Fill the Blanks is currently available for Python files."""
    SessionLocal, _ = test_db
    user = create_user(github_id=8991, username="non_python_user")

    report_md = """
# Reverse Architecture Report

## 3. Step-by-Step Architectural Milestones

### Milestone 0: Go Leaf Utilities
**[HIGH CONFIDENCE]** -- *Go Leaf Helpers*
**Overview:** Core Go helper routines.
**Domain Composition:** 100% Core
**Included Files:**
- `cmd/server/main.go`
"""

    go_code = """package main

import "fmt"

func Helper() {
    fmt.Println("Hello")
}
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/go-repo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={
                "nodes": [
                    {
                        "id": "cmd/server/main.go",
                        "path": "cmd/server/main.go",
                        "tier": 0,
                        "name": "cmd/server/main.go",
                        "source_code": go_code,
                    },
                ],
                "edges": [],
            },
        )
        job_id = job.id

    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    resp = client.get(f"/report/{job_id}", cookies={"access_token": token})
    assert resp.status_code == 200
    html_text = resp.text

    # Milestone 0 should have disabled Fill the Blanks tab with clear non-Python tooltip
    assert 'id="mode-btn-fill-0"' in html_text
    assert 'disabled' in html_text
    assert "Fill the Blanks mode is currently available for Python files. Try Guess It or Just Read It for this file instead." in html_text
    assert "Syntax error" not in html_text













