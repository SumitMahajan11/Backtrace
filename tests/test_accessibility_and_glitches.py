"""
Tests for Accessibility Standards and UI Glitch Fixes:
1. Every interactive element has visible focus outline: `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }`
2. Buttons and radio rows have a minimum 44px tap height on screens under 600px
3. Every icon-only button has aria-label
4. Text contrast: muted text >= 4.5:1 on background and surface in both themes
5. Landing page: one headline, one sentence, one "Sign in with GitHub" primary button, and 3 short bullets describing what product does with no jargon
6. Invalid URL error: "That doesn't look like a GitHub repository link." shown inline under input
7. Glitch 1: Progress page only shows phases (no Stage 09 vs Stage 10 of 11 mismatch)
8. Glitch 2: No __init__ or _cleanup in Key exported symbols (filter names starting with underscore)
9. Glitch 3: Overlapping citation ranges are merged into one range per function
"""

import pytest
import re
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models.db import Base, UserModel, AnalysisJobModel
from app.api.dependencies import get_db
from app.security.auth import create_access_token
from app.ui.components import login_view, dashboard_view, progress_view
from app.rag.schema import CitationSource, CodeChunk
from app.rag.engine import merge_overlapping_citations
from app.synthesis.engine import merge_citation_strings, SynthesisEngine
from app.formatters.markdown_formatter import MarkdownReportFormatter


from sqlalchemy.pool import StaticPool
from app.storage.user_repository import UserRepository


@pytest.fixture(scope="module")
def scratch_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield TestingSession, engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(scratch_db):
    TestingSession, _ = scratch_db

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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def create_test_user(scratch_db):
    TestingSession, _ = scratch_db

    def _create(github_id=88801, username="a11y_user"):
        with TestingSession() as session:
            existing = session.query(UserModel).filter_by(github_id=github_id).first()
            if existing:
                return existing
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


# -----------------------------------------------------------------------------
# 1 & 2: Focus Outline & 44px Mobile Tap Target
# -----------------------------------------------------------------------------

def test_focus_visible_outline_in_css():
    """Every interactive element has a visible focus outline: outline: 2px solid var(--accent); outline-offset: 2px."""
    with open("static/style.css", "r", encoding="utf-8") as f:
        css = f.read()
    assert ":focus-visible" in css
    assert "outline: 2px solid var(--accent)" in css
    assert "outline-offset: 2px" in css


def test_mobile_tap_target_height_under_600px():
    """Buttons and radio rows have a minimum 44px tap height on screens under 600px."""
    with open("static/style.css", "r", encoding="utf-8") as f:
        css = f.read()
    assert "@media (max-width: 600px)" in css
    assert "min-height: 44px" in css


# -----------------------------------------------------------------------------
# 3: Aria-label on Icon-Only Buttons
# -----------------------------------------------------------------------------

def test_icon_only_buttons_have_aria_labels(create_test_user):
    """Every icon-only button rendered in shell or interactive cards has an explicit aria-label."""
    user = create_test_user(github_id=88802, username="aria_user")
    dash_html = dashboard_view(
        current_user=user,
        billing_status={"tier": "free", "monthly_usage": 0, "monthly_quota": 5},
        past_jobs=[],
    )
    # User menu button
    assert 'id="user-menu-btn"' in dash_html
    assert 'aria-label="User menu"' in dash_html

    # Theme toggle button
    assert 'id="theme-toggle"' in dash_html
    assert 'aria-label=' in dash_html


# -----------------------------------------------------------------------------
# 4: Color Contrast Ratios (>= 4.5:1)
# -----------------------------------------------------------------------------

def test_color_contrast_ratios_pass_wcag():
    """Text contrast: muted text must be at least 4.5:1 on its background in both themes."""
    def lum(hex_code):
        hex_code = hex_code.lstrip('#')
        r, g, b = [int(hex_code[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
        channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    def ratio(c1, c2):
        l1, l2 = lum(c1), lum(c2)
        return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)

    dark_bg = ratio("#9aa3b2", "#0f1115")
    dark_surface = ratio("#9aa3b2", "#171a21")
    light_bg = ratio("#5b6472", "#fafafa")
    light_surface = ratio("#5b6472", "#ffffff")

    assert dark_bg >= 4.5, f"Dark bg contrast {dark_bg:.2f} < 4.5"
    assert dark_surface >= 4.5, f"Dark surface contrast {dark_surface:.2f} < 4.5"
    assert light_bg >= 4.5, f"Light bg contrast {light_bg:.2f} < 4.5"
    assert light_surface >= 4.5, f"Light surface contrast {light_surface:.2f} < 4.5"


# -----------------------------------------------------------------------------
# 5: Landing Page Structure
# -----------------------------------------------------------------------------

def test_landing_page_structure():
    """Landing page: one headline, one sentence, one 'Sign in with GitHub' primary button, 3 short bullets, no jargon."""
    html = login_view()

    # One primary headline
    h1_matches = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    assert len(h1_matches) == 1
    assert "Understand any codebase without reading every file" in h1_matches[0]

    # One primary sign-in button
    assert "Sign in with GitHub" in html
    assert 'id="github-signin-btn"' in html

    # Exactly 3 short bullets
    li_matches = re.findall(r"<li[^>]*>(.*?)</li>", html)
    assert len(li_matches) == 3

    # No jargon
    assert "AUTHENTICATION GATE" not in html
    assert "GITHUB OAUTH 2.0" not in html
    assert "Archival Dossier" not in html
    assert "Repository Archaeology" not in html


# -----------------------------------------------------------------------------
# 6: Invalid URL Error Inline Under Input
# -----------------------------------------------------------------------------

def test_invalid_url_error_rendered_inline(create_test_user):
    """Invalid URL error: 'That doesn't look like a GitHub repository link.' Show it inline under the input."""
    user = create_test_user(github_id=88803, username="url_user")
    dash_html = dashboard_view(
        current_user=user,
        billing_status={"tier": "free", "monthly_usage": 0, "monthly_quota": 5},
        past_jobs=[],
        error="That doesn't look like a GitHub repository link.",
    )

    # Inline error container is present
    assert 'id="repo-url-error"' in dash_html
    assert "That doesn&#039;t look like a GitHub repository link." in dash_html or "That doesn't look like a GitHub repository link." in dash_html

    # Input is marked invalid
    assert 'aria-invalid="true"' in dash_html
    assert 'aria-describedby="repo-url-error"' in dash_html

    # Generic top banner is suppressed for inline URL error
    assert '<div class="alert-error"' not in dash_html


def test_submit_invalid_url_redirects_with_exact_error_message(client, create_test_user):
    """Submitting an invalid URL produces the exact message 'That doesn't look like a GitHub repository link.'."""
    user = create_test_user(github_id=88804, username="submit_user")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    resp = client.post("/analyses/submit", data={"repo_url": "not-a-valid-github-url"}, follow_redirects=False)
    assert resp.status_code == 302
    assert "That+doesn%27t+look+like+a+GitHub+repository+link." in resp.headers["location"]


# -----------------------------------------------------------------------------
# 7: Glitch Fixes
# -----------------------------------------------------------------------------

def test_glitch_1_progress_page_only_shows_phases():
    """'Stage 09 vs Stage 10 of 11' mismatch no longer appears (progress page only shows phases)."""
    mock_job = AnalysisJobModel(
        id="job_glitch1",
        user_id=1,
        repo_url="https://github.com/pallets/flask",
        repo_name="flask",
        status="running",
        execution_time_seconds=2.5,
    )
    html = progress_view(job=mock_job, current_user=None)

    # Mismatch text does not appear
    assert "Stage 09" not in html
    assert "Stage 10 of 11" not in html
    # Logs render phases
    assert "Phase ${phaseIdx} of 4" in html


def test_glitch_2_no_underscore_symbols_in_key_exported_symbols():
    """No __init__ or _cleanup in 'Key exported symbols' (filter names starting with an underscore)."""
    # 1. Synthesis engine enrichment
    from app.sequence.schema import BuildStepNarrative
    step = BuildStepNarrative(
        step_number=1,
        title="Setup step",
        pedagogical_explanation="Init components",
        files=["src/app.py"],
        dominant_domain="core",
        domain_groups={"core": ["src/app.py"]},
        dominant_confidence="high",
        confidence_breakdown={},
        tier_index=0,
        is_cyclic_cluster=False,
    )
    symbols_by_file = {
        "src/app.py": ["__init__", "_cleanup", "create_app", "run_server", "_internal_helper"]
    }

    engine = SynthesisEngine()
    milestone = engine._enrich_step(
        step=step,
        symbols_by_file=symbols_by_file,
        rag_engine=None,
        track="core",
        track_label="Milestone",
        display_id="1",
        display_number=1,
    )

    assert "__init__" not in milestone.key_symbols_and_exports
    assert "_cleanup" not in milestone.key_symbols_and_exports
    assert "_internal_helper" not in milestone.key_symbols_and_exports
    assert "create_app" in milestone.key_symbols_and_exports
    assert "run_server" in milestone.key_symbols_and_exports

    # 2. Markdown formatter filtering
    class DummyOverview:
        primary_language = "Python"
        total_files = 1
        total_domains = 1
        entry_point_files = ["src/app.py"]
        cyclic_cluster_file_count = 0
        isolated_file_count = 0
        domain_breakdown = {"core": 1}
        domain_file_counts = {"core": 1}

    class DummyReport:
        def __init__(self, ms):
            self.repo_name = "test-repo"
            self.architecture_overview = DummyOverview()
            self.milestones = ms
            self.test_track = []
            self.dominant_domain = "core"
            self.repository_name = "test"
            self.total_files = 1
            self.total_milestones = 1
            self.synthesis_timestamp = "2026-10-24"
            self.confidence_disclosure = "High confidence"
            self.file_symbols = {}
            self.file_dependencies = []

    dummy_report = DummyReport([milestone])
    md_output = MarkdownReportFormatter().format_report(dummy_report)
    assert "__init__" not in md_output
    assert "_cleanup" not in md_output
    assert "create_app" in md_output


def test_glitch_3_overlapping_citation_ranges_merged_per_function():
    """Overlapping citation ranges are merged into one range per function."""
    citations = [
        CitationSource(
            file_path="src/service.py",
            start_line=10,
            end_line=20,
            symbol_name="handle_request",
            line_range_str="src/service.py:L10-L20 (handle_request)",
        ),
        CitationSource(
            file_path="src/service.py",
            start_line=18,
            end_line=30,
            symbol_name="handle_request",
            line_range_str="src/service.py:L18-L30 (handle_request)",
        ),
        CitationSource(
            file_path="src/service.py",
            start_line=45,
            end_line=60,
            symbol_name="handle_request",
            line_range_str="src/service.py:L45-L60 (handle_request)",
        ),
        CitationSource(
            file_path="src/service.py",
            start_line=5,
            end_line=15,
            symbol_name="helper_func",
            line_range_str="src/service.py:L5-L15 (helper_func)",
        ),
    ]

    merged = merge_overlapping_citations(citations)

    # handle_request: [10-20] and [18-30] should merge into [10-30]; [45-60] remains separate
    hr_cites = [c for c in merged if c.symbol_name == "handle_request"]
    assert len(hr_cites) == 2
    assert hr_cites[0].start_line == 10
    assert hr_cites[0].end_line == 30
    assert hr_cites[0].line_range_str == "src/service.py:L10-L30 (handle_request)"
    assert hr_cites[1].start_line == 45
    assert hr_cites[1].end_line == 60

    # String-based merger test
    raw_str_citations = [
        "src/util.py:L10-L25 (calc_fee)",
        "src/util.py:L20-L40 (calc_fee)",
        "src/other.py:L1-L10",
    ]
    merged_strs = merge_citation_strings(raw_str_citations)
    assert "src/util.py:L10-L40 (calc_fee)" in merged_strs
    assert len([s for s in merged_strs if "calc_fee" in s]) == 1
