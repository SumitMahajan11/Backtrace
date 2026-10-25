import os
import re
import pytest
from starlette.testclient import TestClient
from app.main import app


def test_default_frontend_version(monkeypatch):
    """Default FRONTEND_VERSION gives active_frontend() == '1'."""
    monkeypatch.delenv("FRONTEND_VERSION", raising=False)
    from app.ui import active_frontend
    assert active_frontend() == "1"


def test_frontend_version_2_switch_and_fallback(monkeypatch):
    """FRONTEND_VERSION=2 gives '2' and a name missing in frontend2 still resolves (falls back)."""
    monkeypatch.setenv("FRONTEND_VERSION", "2")
    from app.ui import active_frontend
    assert active_frontend() == "2"

    import app.ui
    import app.frontend1.components as fe1_comp
    from app.ui.components import pricing_view, report_view

    # Verify fallback from app.ui and app.ui.components
    assert getattr(app.ui, "pricing_view") is fe1_comp.pricing_view
    assert pricing_view is fe1_comp.pricing_view
    assert report_view is fe1_comp.report_view

    # When frontend2 defines an attribute, frontend2 version takes precedence
    import app.frontend2
    monkeypatch.setattr(app.frontend2, "test_v2_component", "rendered_v2", raising=False)
    assert getattr(app.ui, "test_v2_component") == "rendered_v2"


def test_static_assets_status_and_content_type():
    """Verify /static/style.css, /static/highlight.min.js, /static/highlight.min.css return 200 with right content-type."""
    client = TestClient(app)

    css_res = client.get("/static/style.css")
    assert css_res.status_code == 200
    assert "text/css" in css_res.headers.get("content-type", "")

    js_res = client.get("/static/highlight.min.js")
    assert js_res.status_code == 200
    assert "javascript" in js_res.headers.get("content-type", "")

    hl_css_res = client.get("/static/highlight.min.css")
    assert hl_css_res.status_code == 200
    assert "text/css" in hl_css_res.headers.get("content-type", "")


def test_login_and_static_urls():
    """Verify /login returns 200 and every /static/... URL found in it returns 200."""
    client = TestClient(app)
    login_res = client.get("/login")
    assert login_res.status_code == 200

    static_urls = set(re.findall(r'["\'](/static/[^"\'\s>]+)["\']', login_res.text))
    assert len(static_urls) > 0, "No static asset URLs found in /login page"

    for url in sorted(static_urls):
        res = client.get(url)
        assert res.status_code == 200, f"Static URL {url} in /login returned {res.status_code}"
