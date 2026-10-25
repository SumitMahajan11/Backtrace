import os
import re
import socket
import threading
import time
import pytest
import uvicorn
from playwright.sync_api import sync_playwright
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user_optional, get_db
from app.db.session import Base
from app.main import app
from app.models.db import UserModel
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
def create_user(test_db):
    TestingSessionLocal, _ = test_db

    def _create(github_id=54321, username="test_shell_user"):
        with TestingSessionLocal() as session:
            user = UserModel(
                github_id=github_id,
                github_username=username,
                email=f"{username}@example.com",
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    return _create


def test_frontend2_static_css_assets_status_and_type(client):
    """Verify /static/frontend2/tokens.css, base.css, shell.css return 200 text/css."""
    for asset in ["tokens.css", "base.css", "shell.css"]:
        resp = client.get(f"/static/frontend2/{asset}")
        assert resp.status_code == 200, f"/static/frontend2/{asset} returned {resp.status_code}"
        assert "text/css" in resp.headers.get("content-type", ""), f"/static/frontend2/{asset} content-type is {resp.headers.get('content-type')}"


def test_frontend2_login_and_static_urls(client, monkeypatch):
    """With FRONTEND_VERSION=2, GET /login returns 200 and every /static/... URL in it returns 200."""
    monkeypatch.setenv("FRONTEND_VERSION", "2")
    resp = client.get("/login")
    assert resp.status_code == 200
    html = resp.text

    static_urls = set(re.findall(r'["\'](/static/[^"\'\s>]+)["\']', html))
    assert len(static_urls) > 0, "No static asset URLs found in /login"

    for url in sorted(static_urls):
        asset_resp = client.get(url)
        assert asset_resp.status_code == 200, f"Static URL {url} in /login returned {asset_resp.status_code}"


def test_frontend2_stylesheets_and_no_external_cdns(client, monkeypatch):
    """The HTML contains the 3 stylesheet links and no http(s)://cdn, googleapis or tailwind references."""
    monkeypatch.setenv("FRONTEND_VERSION", "2")
    resp = client.get("/login")
    assert resp.status_code == 200
    html = resp.text

    assert '<link rel="stylesheet" href="/static/frontend2/tokens.css">' in html
    assert '<link rel="stylesheet" href="/static/frontend2/base.css">' in html
    assert '<link rel="stylesheet" href="/static/frontend2/shell.css">' in html

    # Assert no external CDNs, googleapis or tailwind references
    assert re.search(r"https?://[^\s\"']*cdn[^\s\"']*", html, re.I) is None
    assert "googleapis" not in html
    assert "tailwind" not in html


def test_frontend2_bottom_tab_bar_presence(client, create_user, test_db, monkeypatch):
    """Bottom tab bar markup exists on a report page and not on /dashboard."""
    monkeypatch.setenv("FRONTEND_VERSION", "2")
    user = create_user(github_id=989801, username="f2_test_user")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    SessionLocal, _ = test_db
    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/owner/f2-repo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown="# Report",
            graph_data={"nodes": [{"id": "node1"}]},
            quiz_data={"questions": []},
        )
        job_id = job.id

    # On dashboard: no bottom bar
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    assert "report-bottom-bar" not in resp_dash.text
    assert "f2-bottom-bar" not in resp_dash.text

    # On report page: bottom bar exists
    resp_rep = client.get(f"/report/{job_id}")
    assert resp_rep.status_code == 200
    assert "report-bottom-bar" in resp_rep.text
    assert "f2-bottom-bar" in resp_rep.text


def test_frontend2_xss_escaping_in_shell(monkeypatch):
    """XSS: a hostile username and repo name are escaped in the shell."""
    monkeypatch.setenv("FRONTEND_VERSION", "2")
    from app.ui.components import page_shell
    from unittest.mock import MagicMock

    hostile_username = '<img src=x onerror=alert("xss_user")>'
    hostile_repo = '<script>alert("xss_repo")</script>'

    mock_user = MagicMock()
    mock_user.github_username = hostile_username
    mock_user.avatar_url = ""

    shell_html = page_shell(
        title=f"Architecture Report: {hostile_repo}",
        content="<div>Safe Content</div>",
        current_user=mock_user,
        active_route="/report/123",
    )

    # Raw script or img payload tags must not exist in output HTML
    assert '<script>alert("xss_repo")</script>' not in shell_html
    assert '<img src=x onerror=alert("xss_user")>' not in shell_html
    assert "&lt;script&gt;alert" in shell_html
    assert "&lt;img src=x" in shell_html


def test_frontend2_playwright_responsiveness_and_shell(test_db, monkeypatch):
    """
    Playwright (real uvicorn server, FRONTEND_VERSION=2, no set_content):
    At widths 390, 768, 1440 on /login and a report page, assert document.documentElement.scrollWidth <= window.innerWidth
    and, at 390, the bottom bar is visible and at 1440 it is not. Save screenshots to scratch/f2_shell/.
    """
    monkeypatch.setenv("FRONTEND_VERSION", "2")
    os.makedirs("scratch/f2_shell", exist_ok=True)

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
            github_id=88123,
            github_username="pw_f2_user",
            email="pw_f2@example.com",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user_id,
            repo_url="https://github.com/expressjs/express",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown="# Express Architecture Report\n\n- Fast, unopinionated, minimalist web framework.",
            graph_data={"nodes": [{"id": "app"}, {"id": "router"}], "edges": [{"from": "app", "to": "router"}]},
            quiz_data={"questions": [{"question": "What is Express?", "options": ["Framework", "DB"], "answer": "Framework"}]},
        )
        job_id = job.id

    token = create_access_token(
        user_id=user_id,
        github_id=88123,
        github_username="pw_f2_user",
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

            targets = [
                ("login", f"http://127.0.0.1:{port}/login"),
                ("report", f"http://127.0.0.1:{port}/report/{job_id}"),
            ]
            widths = [390, 768, 1440]

            for page_name, url in targets:
                for width in widths:
                    page.set_viewport_size({"width": width, "height": 844})
                    page.goto(url, wait_until="networkidle")

                    # Verify no horizontal scrolling: scrollWidth <= innerWidth
                    scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
                    inner_width = page.evaluate("() => window.innerWidth")
                    assert scroll_width <= inner_width, f"{page_name} has horizontal scroll at width {width}: {scroll_width} > {inner_width}"

                    # Capture screenshot to scratch/f2_shell/
                    shot_path = os.path.join("scratch", "f2_shell", f"{page_name}_{width}.png")
                    page.screenshot(path=shot_path, full_page=False)

                    # On report page, test bottom bar visibility
                    if page_name == "report":
                        bottom_bar = page.locator("#report-bottom-bar")
                        if width == 390:
                            assert bottom_bar.is_visible(), f"Expected bottom bar to be visible at width {width}"
                        elif width == 1440:
                            assert not bottom_bar.is_visible(), f"Expected bottom bar to NOT be visible at width {width}"

            browser.close()
    finally:
        server.should_exit = True
        server_thread.join(timeout=3)
        app.dependency_overrides.clear()
