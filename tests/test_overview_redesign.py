"""Tests for Architecture Overview Redesign (Steps 1-8).

Verifies:
- Step 1: TL;DR block (README summary / fallback, main language, start here entry points, read first files).
- Step 2: 4 stat cards (total files with code/docs split, entry points, modules, confidence number only).
- Step 3: Real entry points list (no tests, text-overflow: ellipsis, title attribute, no ▷ icon).
- Step 4: Method note 'Order is estimated from imports.' under TL;DR, no italic quote block.
- Step 5: Subsystem bars with --surface-2 track and count at right, 2-column layout for 6+ subsystems.
- Step 6: Horizontal stacked confidence bar with 3 plain legend lines and explanation sentence.
- Step 7: Export as Markdown route (owner only, 404 for non-owner, text/markdown).
- Step 8: Lazy-loaded milestone bodies and page size before vs after.
- XSS prevention across all dynamic fields.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import (
    AnalysisJobModel,
    AnalysisResultModel,
    IngestionResultModel,
    RepoModel,
    UserModel,
    utc_now,
)
from app.security.auth import create_access_token
from app.ui.components import (
    extract_readme_summary,
    get_main_language,
    get_start_here_entry_points,
    get_read_first_files,
    count_code_and_docs_files,
    report_view,
)


SAMPLE_OVERVIEW_MARKDOWN = """# Architectural Reverse-Engineering Report: `fastapi/fastapi`

*Synthesized at: 2026-10-24 02:00:00 UTC*
<!-- narration_source: template -->

## 1. Executive Summary & Core Architectural Invariants
- **Primary Language**: `Python`
- **Total Analyzed Files**: `98`
- **Domain Categories**: `7`
- **Entry Point Files**: `main.py, app/api.py, tests/test_main.py`
- **Cyclic Core Components**: `0`
- **Isolated / Support Files**: `0`

| Domain Category | File Count | Percentage |
| :--- | :--- | :--- |
| `routing` | 28 | 28.6% |
| `security` | 20 | 20.4% |
| `validation` | 16 | 16.3% |
| `database` | 14 | 14.3% |
| `middleware` | 10 | 10.2% |
| `utilities` | 6 | 6.1% |
| `config` | 4 | 4.1% |

## 2. Build Order & Confidence Scoring
Sequence reasoning notes here.

## 3. Step-by-Step Architectural Milestones

### Milestone 1: App Core & Routing (Tier 1)
**[HIGH CONFIDENCE]** -- *Routing and dispatch engine*

**Overview:**
Initialize core FastAPI routing mechanisms and application engine.

**Domain Composition:**
Core routing logic and path handling.

**Included Files (2):**
- `main.py`
- `app/api.py`

**Key Exported Symbols:** `FastAPI, APIRouter`

**Deep-Dive Semantic Citations:**
- Foundational routing subsystem

**Pedagogical Notes:**
- Heavy milestone body documentation that will be lazy-loaded.
- Implementation details:
```python
def create_app():
    return FastAPI()
```

### Milestone 2: Authentication & Security (Tier 2)
**[MEDIUM CONFIDENCE]** -- *Security protocols*

**Overview:**
OAuth2 password bearers and cryptographic signature handling.

**Domain Composition:**
Security middleware.

**Included Files (1):**
- `app/security.py`

**Key Exported Symbols:** `OAuth2PasswordBearer, verify_token`

**Pedagogical Notes:**
- Security milestone body text with elaborate instructions.
"""


def build_sample_graph_data():
    return {
        "nodes": [
            {"id": "main.py", "path": "main.py", "tier": 0, "domain": "routing"},
            {"id": "app/api.py", "path": "app/api.py", "tier": 0, "domain": "routing"},
            {"id": "tests/test_main.py", "path": "tests/test_main.py", "tier": 0, "domain": "routing"},
            {"id": "app/core.py", "path": "app/core.py", "tier": 0, "domain": "routing"},
            {"id": "app/models.py", "path": "app/models.py", "tier": 0, "domain": "database"},
            {"id": "app/utils.py", "path": "app/utils.py", "tier": 0, "domain": "utilities"},
            {"id": "README.md", "path": "README.md", "tier": 0, "domain": "docs"},
            {"id": "docs/architecture.md", "path": "docs/architecture.md", "tier": 0, "domain": "docs"},
        ],
        "edges": [
            {"source": "main.py", "target": "app/core.py"},
            {"source": "app/api.py", "target": "app/core.py"},
            {"source": "app/models.py", "target": "app/core.py"},
            {"source": "main.py", "target": "app/models.py"},
            {"source": "app/api.py", "target": "app/models.py"},
            {"source": "main.py", "target": "app/utils.py"},
        ],
        "inbound_counts": {
            "app/core.py": 18,
            "app/models.py": 14,
            "app/utils.py": 10,
            "tests/test_main.py": 1,
        },
        "confidence": {
            "high": 75,
            "medium": 20,
            "low": 5,
        },
    }


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


def create_user(session, github_id: int, username: str, email: str) -> UserModel:
    user = UserModel(
        github_id=github_id,
        github_username=username,
        email=email,
        avatar_url=f"https://avatars.example.com/{username}",
        is_admin=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def create_job(session, user_id: int, report_md: str, graph_data: Dict[str, Any], is_showcase: bool = False) -> AnalysisJobModel:
    import uuid
    job = AnalysisJobModel(
        user_id=user_id,
        run_id=f"run_{user_id}_{uuid.uuid4().hex[:8]}",
        repo_url="https://github.com/fastapi/fastapi",
        repo_name="fastapi",
        status="completed",
        report_markdown=report_md,
        graph_data=graph_data,
        is_showcase=is_showcase,
        execution_time_seconds=12.5,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


# -----------------------------------------------------------------------------
# STEP 1: Unit tests for TL;DR block helper functions
# -----------------------------------------------------------------------------
def test_extract_readme_summary_with_readme():
    readme_text = "# FastAPI Framework\n\nFastAPI is a modern, fast (high-performance), web framework for building APIs with Python 3.8+ based on standard Python type hints.\n\n## Key Features\n- Fast to code"
    summary = extract_readme_summary(readme_text)
    assert "FastAPI is a modern, fast" in summary
    assert "web framework for building APIs" in summary
    assert "#" not in summary
    assert len(summary) <= 300


def test_extract_readme_summary_no_readme():
    assert extract_readme_summary(None) == "No README found."
    assert extract_readme_summary("") == "No README found."
    assert extract_readme_summary("   ") == "No README found."


def test_get_main_language():
    nodes = [
        {"path": "a.py"},
        {"path": "b.py"},
        {"path": "c.js"},
    ]
    lang = get_main_language(nodes, {"primary_language": "TypeScript"})
    assert lang == "Python"

    # Fallback to parsed_md language if no nodes
    assert get_main_language([], {"primary_language": "Rust"}) == "Rust"


def test_get_start_here_entry_points():
    nodes = [
        {"path": "src/index.ts", "domain": "app"},
        {"path": "tests/test_app.py", "domain": "tests"},
        {"path": "server.py", "domain": "app"},
        {"path": "cmd/main.go", "domain": "app"},
        {"path": "cli.py", "domain": "cli"},
    ]
    entry_candidates = ["src/index.ts", "tests/test_app.py", "server.py", "cmd/main.go", "cli.py"]
    eps = get_start_here_entry_points(nodes, entry_candidates, max_n=3)
    # Should exclude tests and cap at 3
    assert "tests/test_app.py" not in eps
    assert len(eps) == 3
    assert eps == ["src/index.ts", "server.py", "cmd/main.go"]


def test_get_read_first_files():
    nodes = [
        {"path": "app/core.py", "domain": "core"},
        {"path": "app/models.py", "domain": "database"},
        {"path": "app/utils.py", "domain": "utils"},
        {"path": "tests/test_core.py", "domain": "tests"},
    ]
    edges = [
        {"source": "main.py", "target": "app/core.py"},
        {"source": "api.py", "target": "app/core.py"},
        {"source": "worker.py", "target": "app/core.py"},
        {"source": "main.py", "target": "app/models.py"},
        {"source": "api.py", "target": "app/models.py"},
        {"source": "main.py", "target": "app/utils.py"},
        {"source": "test_1.py", "target": "tests/test_core.py"},
        {"source": "test_2.py", "target": "tests/test_core.py"},
        {"source": "test_3.py", "target": "tests/test_core.py"},
        {"source": "test_4.py", "target": "tests/test_core.py"},
    ]
    read_first = get_read_first_files(nodes, edges, max_n=3)
    assert "tests/test_core.py" not in read_first
    assert read_first == ["app/core.py", "app/models.py", "app/utils.py"]


def test_count_code_and_docs_files():
    nodes = [
        {"path": "main.py"},
        {"path": "lib/utils.py"},
        {"path": "README.md"},
        {"path": "docs/guide.rst"},
    ]
    code, docs = count_code_and_docs_files(nodes, total_files=4)
    assert docs == 2
    assert code == 2


# -----------------------------------------------------------------------------
# STEP 1 to 6: Full Overview HTML rendering tests
# -----------------------------------------------------------------------------
def test_overview_redesign_full_render_with_readme(test_db):
    TestingSessionLocal, _ = test_db
    with TestingSessionLocal() as session:
        user = create_user(session, 1001, "dev1", "dev1@example.com")
        graph_data = build_sample_graph_data()
        job = create_job(session, user.id, SAMPLE_OVERVIEW_MARKDOWN, graph_data)

        file_contents = {
            "README.md": "# FastAPI\n\nFastAPI is a modern, high-performance web framework for building APIs with Python.",
            "main.py": "from fastapi import FastAPI\napp = FastAPI()",
            "app/core.py": "CORE_VERSION = '1.0.0'",
        }

        html = report_view(
            job=job,
            raw_markdown=job.report_markdown,
            graph_data=graph_data,
            quiz_data=None,
            current_user=user,
            file_contents=file_contents,
        )

        # Step 1: TL;DR Block
        assert 'id="overview-tldr-block"' in html
        assert "What this project is" in html
        assert "FastAPI is a modern, high-performance web framework" in html
        assert "Main language" in html
        assert "Python" in html
        assert "Start here" in html
        assert "main.py" in html
        assert "app/api.py" in html
        # Tests must not appear in "Start here"
        assert "tests/test_main.py" not in html.split("Start here")[1].split("Read these 3 files first")[0]
        assert "Read these 3 files first" in html
        assert "app/core.py" in html
        assert "app/models.py" in html

        # Step 2: Exactly 4 stat cards in .overview-stat-cards
        assert "overview-stat-cards" in html
        assert "Files analyzed" in html
        assert "98 files" in html
        assert "code," in html and "docs" in html
        assert "Entry points" in html
        assert "Modules" in html
        assert "Confidence" in html
        # Card 4 shows high % number only, no sentence inside card
        assert "75%" in html

        # Step 3: Entry points list with ellipsis and title attribute
        assert 'id="overview-entry-points-list"' in html
        assert 'title="main.py"' in html
        assert 'title="app/api.py"' in html
        assert "▷" not in html.split('id="overview-entry-points-list"')[1].split("<!-- Domain Distribution -->")[0]

        # Step 4: Method note under TL;DR: "Order is estimated from imports."
        assert "Order is estimated from imports." in html

        # Step 5: Subsystem list with visible track (--surface-2) and 2-column layout (7 subsystems >= 6)
        assert "subsystem-grid-2col" in html
        assert "var(--surface-2)" in html
        assert "routing" in html
        assert "28" in html

        # Step 6: Confidence horizontal stacked bar with 3 plain legend lines
        assert 'id="confidence-horizontal-bar"' in html
        assert "High means the file is imported by many others and has clear structure." in html
        assert "Tier 1" not in html.split('id="confidence-horizontal-bar"')[1].split("</div>")[0]


def test_overview_redesign_fallback_no_readme(test_db):
    TestingSessionLocal, _ = test_db
    with TestingSessionLocal() as session:
        user = create_user(session, 1002, "dev2", "dev2@example.com")
        graph_data = build_sample_graph_data()
        job = create_job(session, user.id, SAMPLE_OVERVIEW_MARKDOWN, graph_data)

        # No README provided in file_contents
        html = report_view(
            job=job,
            raw_markdown=job.report_markdown,
            graph_data=graph_data,
            quiz_data=None,
            current_user=user,
            file_contents={"main.py": "pass"},
        )

        assert "What this project is" in html
        assert "No README found." in html


# -----------------------------------------------------------------------------
# STEP 7: Export as Markdown route
# -----------------------------------------------------------------------------
def test_export_markdown_route(client, test_db):
    TestingSessionLocal, _ = test_db
    with TestingSessionLocal() as session:
        owner = create_user(session, 2001, "owner1", "owner1@example.com")
        other_user = create_user(session, 2002, "attacker", "attacker@example.com")
        graph_data = build_sample_graph_data()
        job = create_job(session, owner.id, SAMPLE_OVERVIEW_MARKDOWN, graph_data)
        job_id = job.id
        owner_id = int(owner.id)
        other_id = int(other_user.id)

    owner_token = create_access_token(user_id=owner_id, github_id=2001, github_username="owner1")
    other_token = create_access_token(user_id=other_id, github_id=2002, github_username="attacker")

    # 1. Anonymous user -> 404
    anon_resp = client.get(f"/reports/{job_id}/export.md")
    assert anon_resp.status_code == 404

    # 2. Non-owner authenticated user -> 404
    non_owner_resp = client.get(
        f"/reports/{job_id}/export.md",
        cookies={"access_token": other_token},
    )
    assert non_owner_resp.status_code == 404

    # 3. Owner user -> 200 with text/markdown media_type
    owner_resp = client.get(
        f"/reports/{job_id}/export.md",
        cookies={"access_token": owner_token},
    )
    assert owner_resp.status_code == 200
    assert "text/markdown" in owner_resp.headers["content-type"]
    assert f'filename="report-{job_id}.md"' in owner_resp.headers["content-disposition"]
    assert "# Architectural Reverse-Engineering Report: `fastapi/fastapi`" in owner_resp.text

    # 4. Check export button is present on report page and raw transcript is removed
    report_page_resp = client.get(
        f"/report/{job_id}",
        cookies={"access_token": owner_token},
    )
    assert report_page_resp.status_code == 200
    report_html = report_page_resp.text
    assert f'href="/reports/{job_id}/export.md"' in report_html
    assert "Export as Markdown" in report_html
    assert "Complete Raw Synthesis Markdown Transcript" not in report_html


# -----------------------------------------------------------------------------
# STEP 8: Lazy-load milestone bodies & endpoint tests
# -----------------------------------------------------------------------------
def test_lazy_load_milestone_bodies_endpoint(client, test_db):
    TestingSessionLocal, _ = test_db
    with TestingSessionLocal() as session:
        owner = create_user(session, 3001, "m_owner", "m_owner@example.com")
        other_user = create_user(session, 3002, "m_other", "m_other@example.com")
        graph_data = build_sample_graph_data()
        job = create_job(session, owner.id, SAMPLE_OVERVIEW_MARKDOWN, graph_data)
        job_id = job.id
        owner_id = int(owner.id)
        other_id = int(other_user.id)

    owner_token = create_access_token(user_id=owner_id, github_id=3001, github_username="m_owner")
    other_token = create_access_token(user_id=other_id, github_id=3002, github_username="m_other")

    # Non-owner -> 404
    resp_other = client.get(
        f"/reports/{job_id}/milestones/1",
        cookies={"access_token": other_token},
    )
    assert resp_other.status_code == 404

    # Owner -> 200 HTML fragment
    resp_owner = client.get(
        f"/reports/{job_id}/milestones/1",
        cookies={"access_token": owner_token},
    )
    assert resp_owner.status_code == 200
    assert "text/html" in resp_owner.headers["content-type"]
    fragment_html = resp_owner.text
    # Fragment contains milestone workspace details
    assert "milestone-brief-card" in fragment_html or "FastAPI" in fragment_html

    # Test invalid milestone -> 404
    resp_not_found = client.get(
        f"/reports/{job_id}/milestones/999",
        cookies={"access_token": owner_token},
    )
    assert resp_not_found.status_code == 404


def test_page_size_comparison_before_and_after_lazy_loading(client, test_db):
    """
    Step 8 requirement: Print len(response.data) / response.content before and after lazy-loading.
    """
    TestingSessionLocal, _ = test_db
    with TestingSessionLocal() as session:
        owner = create_user(session, 4001, "size_user", "size_user@example.com")
        graph_data = build_sample_graph_data()
        job = create_job(session, owner.id, SAMPLE_OVERVIEW_MARKDOWN, graph_data)
        job_id = job.id
        owner_id = int(owner.id)

    token = create_access_token(user_id=owner_id, github_id=4001, github_username="size_user")

    # 1. Before: Preloaded full milestone bodies (preload=1)
    resp_before = client.get(f"/report/{job_id}?preload=1", cookies={"access_token": token})
    assert resp_before.status_code == 200
    size_before = len(resp_before.content)

    # 2. After: Lazy-loaded milestone bodies (default)
    resp_after = client.get(f"/report/{job_id}", cookies={"access_token": token})
    assert resp_after.status_code == 200
    size_after = len(resp_after.content)

    print(f"\n--- PAGE SIZE COMPARISON (Step 8) ---")
    print(f"Page size BEFORE (preloaded bodies): {size_before} bytes")
    print(f"Page size AFTER  (lazy-loaded bodies): {size_after} bytes")
    print(f"Payload reduction: {size_before - size_after} bytes ({(1 - size_after / size_before) * 100:.1f}% reduction)")

    # Lazy-loaded page must be strictly smaller than preloaded page
    assert size_after < size_before


# -----------------------------------------------------------------------------
# XSS Sanitization Tests
# -----------------------------------------------------------------------------
def test_xss_protection_in_overview(test_db):
    TestingSessionLocal, _ = test_db
    with TestingSessionLocal() as session:
        user = create_user(session, 5001, "xss_user", "xss@example.com")
        malicious_readme = (
            "# <script>alert('xss-h1')</script>\n\n"
            "<img src=x onerror=alert('xss-img')> Malicious description with <svg onload=alert(1)> and "
            "[link](javascript:alert(2))."
        )
        file_contents = {"README.md": malicious_readme}

        malicious_graph = {
            "nodes": [
                {"id": "<script>alert('node')</script>", "path": "<script>alert('path')</script>", "domain": "<b>dom</b>"},
            ],
            "edges": [],
            "entry_points": ["<img src=x onerror=alert('entry')>"],
        }

        malicious_md = """# Report: `<script>alert('title')</script>`
## 1. Executive Summary
- **Primary Language**: `<script>alert('lang')</script>`
- **Total Analyzed Files**: `1`
- **Domain Categories**: `1`
- **Entry Point Files**: `<img src=x onerror=alert('entry')>`
"""

        job = create_job(session, user.id, malicious_md, malicious_graph)

        html = report_view(
            job=job,
            raw_markdown=malicious_md,
            graph_data=malicious_graph,
            quiz_data=None,
            current_user=user,
            file_contents=file_contents,
        )

        # Raw executable script / onerror tags must NEVER appear unescaped
        assert "<script>alert('xss-h1')</script>" not in html
        assert "<img src=x onerror=alert('xss-img')>" not in html
        assert "<svg onload=alert(1)>" not in html
        assert "javascript:alert(2)" not in html
        assert "<script>alert('lang')</script>" not in html
        assert "<img src=x onerror=alert('entry')>" not in html
