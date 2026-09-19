"""Comprehensive Frontend UI, SSE Progress, XSS Sanitization, and IDOR Defense Tests."""

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
    assert "Root-Cause Inquest Ledger" in resp.text
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
