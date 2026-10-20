"""Tests for Sandbox Public Notice Banner, Public Config, and Disabled States.

Verifies:
1. /api/public-config returns sandbox_enabled boolean reflecting SANDBOX_ENABLED.
2. /api/public-config returns strictly only {"sandbox_enabled", "demo_video_url"}.
3. The milestone page contains the exact banner text when disabled, and does not contain it when enabled.
4. The Run button has the disabled attribute when disabled, and enabled when enabled.
5. 503 response from run/submit calls triggers the safe banner text display rather than raw server error messages.
6. Submit button behavior matches requires_execution state (disabled for execution milestones, 'Check structure' for structural_only).
"""

import os
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import UserModel
from app.security.auth import create_access_token
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.user_repository import UserRepository
from app.ui.components import SANDBOX_DISABLED_BANNER_TEXT


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


# =========================================================================
# a) & b) Public Config Endpoint Tests
# =========================================================================

def test_public_config_sandbox_enabled_flag(client, monkeypatch):
    """
    a) /api/public-config returns sandbox_enabled false when SANDBOX_ENABLED=false,
       and true when it is true.
    b) The response has no other keys than the two listed.
    """
    # 1. When SANDBOX_ENABLED=false
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    monkeypatch.setenv("DEMO_VIDEO_URL", "https://example.com/demo.mp4")
    resp_false = client.get("/api/public-config")
    assert resp_false.status_code == 200
    data_false = resp_false.json()
    assert data_false["sandbox_enabled"] is False
    assert data_false["demo_video_url"] == "https://example.com/demo.mp4"
    assert set(data_false.keys()) == {"sandbox_enabled", "demo_video_url"}

    # 2. When SANDBOX_ENABLED=true
    monkeypatch.setenv("SANDBOX_ENABLED", "true")
    resp_true = client.get("/api/public-config")
    assert resp_true.status_code == 200
    data_true = resp_true.json()
    assert data_true["sandbox_enabled"] is True
    assert set(data_true.keys()) == {"sandbox_enabled", "demo_video_url"}

    # 3. When DEMO_VIDEO_URL is unset
    monkeypatch.delenv("DEMO_VIDEO_URL", raising=False)
    resp_empty = client.get("/api/public-config")
    assert resp_empty.status_code == 200
    data_empty = resp_empty.json()
    assert data_empty["demo_video_url"] == ""
    assert set(data_empty.keys()) == {"sandbox_enabled", "demo_video_url"}


# =========================================================================
# c) Milestone Page Banner Tests
# =========================================================================

def test_milestone_page_banner_when_disabled_and_enabled(client, create_user, test_db, monkeypatch):
    """
    c) The milestone page contains the banner text when disabled, and does not contain it when enabled.
       Also verifies video link conditionally appended when demo_video_url is present.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9901, username="sandbox_banner_user")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/sandbox-demo-repo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown="""# Report
## 3. Step-by-Step Architectural Milestones
### Milestone 0: Core
**[HIGH CONFIDENCE]** -- *Core module*
**Included Files:**
- `app/core.py`
""",
            graph_data={
                "nodes": [{"id": "app/core.py", "path": "app/core.py", "tier": 0, "symbols": []}],
                "milestones": [{"tier": 0, "title": "Core", "exported_symbols": []}],
            },
        )
        job_id = job.id

    # 1. When disabled without video URL
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    monkeypatch.delenv("DEMO_VIDEO_URL", raising=False)
    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    assert SANDBOX_DISABLED_BANNER_TEXT in resp.text
    assert "sandbox-disabled-banner" in resp.text
    assert "Watch the video</a>" not in resp.text

    # 2. When disabled with video URL
    monkeypatch.setenv("DEMO_VIDEO_URL", "https://youtube.com/watch?v=12345")
    resp_video = client.get(f"/report/{job_id}")
    assert resp_video.status_code == 200
    assert SANDBOX_DISABLED_BANNER_TEXT in resp_video.text
    assert "Watch the video</a>" in resp_video.text
    assert 'href="https://youtube.com/watch?v=12345"' in resp_video.text

    # 3. When enabled: NO banner, NO video link, looks as before
    monkeypatch.setenv("SANDBOX_ENABLED", "true")
    resp_enabled = client.get(f"/report/{job_id}")
    assert resp_enabled.status_code == 200
    assert SANDBOX_DISABLED_BANNER_TEXT not in resp_enabled.text
    assert "sandbox-disabled-banner" not in resp_enabled.text


# =========================================================================
# d) Run Button Disabled Attribute & Notes Tests
# =========================================================================

def test_run_button_disabled_state_and_notes(client, create_user, test_db, monkeypatch):
    """
    d) The Run button has the disabled attribute when disabled.
       Also verifies the note under the button: 'Run is unavailable on this demo.'
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9902, username="run_button_user")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    report_md = """# Architectural Report
## 3. Step-by-Step Architectural Milestones

### Milestone 0: Core
**[HIGH CONFIDENCE]** -- *Core module*
**Overview:** Core implementation
**Included Files:**
- `core.py`
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/run-btn-repo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={
                "nodes": [{"id": "core.py", "path": "core.py", "tier": 0, "symbols": []}],
                "milestones": [{"tier": 0, "title": "Core", "exported_symbols": []}],
            },
        )
        job_id = job.id

    # 1. When SANDBOX_ENABLED=false: Run button is disabled with note
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html = resp.text

    # Check Run button has disabled attribute
    assert re.search(r'<button\s+[^>]*id="btn-run-0"[^>]*disabled', html) is not None
    assert "Run is unavailable on this demo." in html

    # 2. When SANDBOX_ENABLED=true: Run button is enabled, no note
    monkeypatch.setenv("SANDBOX_ENABLED", "true")
    resp_enabled = client.get(f"/report/{job_id}")
    assert resp_enabled.status_code == 200
    html_enabled = resp_enabled.text

    assert re.search(r'<button\s+[^>]*id="btn-run-0"[^>]*disabled', html_enabled) is None
    assert "Run is unavailable on this demo." not in html_enabled


# =========================================================================
# e) HTTP 503 Handling Shows Banner Text, Not Raw Server Message
# =========================================================================

def test_run_and_submit_503_handler_and_safe_banner(client, create_user, test_db, monkeypatch):
    """
    e) A 503 from the run call shows the banner text, not the raw message.
       Verifies both the server returning 503 when sandbox is disabled,
       and the client-side JavaScript rendering render503Notice with SANDBOX_DISABLED_BANNER_TEXT.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9903, username="503_tester_user")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)
    headers = {"Authorization": f"Bearer {token}"}

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/503-repo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            graph_data={
                "nodes": [{"id": "pkg/mod.py", "path": "pkg/mod.py", "tier": 0, "symbols": []}],
                "milestones": [{"tier": 0, "title": "Foundation", "exported_symbols": []}],
            },
        )
        job_id = job.id

    # Disable sandbox to make /run endpoint return 503 Service Unavailable
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    run_resp = client.post(
        f"/api/attempts/{job_id}/0/run",
        headers=headers,
        json={"submitted_code": "print('hello')", "language": "python"},
    )
    assert run_resp.status_code == 503
    raw_server_detail = run_resp.json()["detail"]
    assert "sandbox" in raw_server_detail.lower()

    # Verify that the report template scripts contain the 503 handler with SANDBOX_DISABLED_BANNER_TEXT
    rep_resp = client.get(f"/report/{job_id}")
    assert rep_resp.status_code == 200
    page_html = rep_resp.text

    assert "render503Notice" in page_html
    assert "SANDBOX_DISABLED_BANNER_TEXT" in page_html
    # Verify that on 503 status, render503Notice is called rather than inserting raw server message
    assert "if (resp.status === 503)" in page_html
    assert "render503Notice(consolePanel, DEMO_VIDEO_URL)" in page_html
    assert "render503Notice(diffPanel, DEMO_VIDEO_URL)" in page_html


# =========================================================================
# Submit Button requires_execution & structural_only Behavior
# =========================================================================

def test_submit_button_structural_vs_execution_modes(client, create_user, test_db, monkeypatch):
    """
    Verifies:
    c) For milestones where requires_execution is true: Submit is disabled with
       'Grading this milestone needs code execution, which is off on this demo.'
    d) For structural_only milestones: Submit stays enabled with label 'Check structure'
       and note 'Structure check only. No points are awarded on this demo.'
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9904, username="grading_mode_user")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)
    headers = {"Authorization": f"Bearer {token}"}

    report_md = """# Architectural Report
## 3. Step-by-Step Architectural Milestones

### Milestone 0: Structural Milestone
**[HIGH CONFIDENCE]** -- *Structural*
**Overview:** Structural milestone overview
**Included Files:**
- `mod0.py`

### Milestone 1: Execution Milestone
**[HIGH CONFIDENCE]** -- *Execution*
**Overview:** Execution milestone overview
**Included Files:**
- `mod1.py`
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/test/grading-repo",
            status="completed",
        )
        # Tier 0 is structural_only; Tier 1 has test_code so requires_execution is True
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={
                "nodes": [
                    {"id": "mod0.py", "path": "mod0.py", "tier": 0, "symbols": []},
                    {"id": "mod1.py", "path": "mod1.py", "tier": 1, "symbols": []},
                ],
                "milestones": [
                    {"tier": 0, "title": "Structural Milestone", "exported_symbols": []},
                    {
                        "tier": 1,
                        "title": "Execution Milestone",
                        "exported_symbols": [],
                        "test_code": "def test_answer(): assert 1 == 1",
                    },
                ],
            },
        )
        job_id = job.id

        from app.services.file_content_service import FileContentService
        FileContentService.persist_file_contents(
            session=session,
            github_url="https://github.com/test/grading-repo",
            file_contents={
                "mod0.py": "def foo(): pass\n",
                "mod1.py": "def bar(): pass\n",
            },
            commit_hash="commithash123",
        )
        session.commit()

    # Check API payload includes requires_execution boolean
    att0_resp = client.get(f"/api/attempts/{job_id}/0", headers=headers)
    assert att0_resp.status_code == 200
    assert att0_resp.json()["requires_execution"] is False
    assert att0_resp.json()["grading_method"] == "structural_only"

    att1_resp = client.get(f"/api/attempts/{job_id}/1", headers=headers)
    assert att1_resp.status_code == 200
    assert att1_resp.json()["requires_execution"] is True
    assert att1_resp.json()["grading_method"] == "real_tests"

    # UI check with SANDBOX_ENABLED=false
    monkeypatch.setenv("SANDBOX_ENABLED", "false")
    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html = resp.text

    # Tier 0 (structural_only): Submit is enabled, label is 'Check structure', note rendered
    assert "Check structure" in html
    assert "Structure check only. No points are awarded on this demo." in html

    # Tier 1 (real_tests / requires_execution): Submit is disabled, note rendered
    assert "Grading this milestone needs code execution, which is off on this demo." in html
    assert re.search(r'<button\s+[^>]*id="btn-submit-1"[^>]*disabled', html) is not None
