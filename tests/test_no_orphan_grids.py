"""
Tests verifying no orphaned stat or KPI cards exist on mobile and tablet viewports.
Covers:
- Viewports 390px and 768px
- Pages: progress (done), report overview, settings, dashboard
- Inspects every element with display:grid or class containing "stat" / "kpi"
- Counts cards per row by getBoundingClientRect().top
- Fails if the last row has fewer cards than the previous rows (except for single-row grids)
"""

import pytest
from playwright.sync_api import sync_playwright

from app.models.db import UserModel, AnalysisJobModel
from app.ui.components import dashboard_view, settings_view, progress_view, report_view


@pytest.fixture
def mock_user():
    return UserModel(id=1, github_id=9901, github_username="tester", email="tester@example.com")


@pytest.fixture
def test_pages_html(mock_user):
    billing = {"tier": "free", "monthly_usage": 2, "monthly_quota": 5}

    # 1. Dashboard
    job1 = AnalysisJobModel(id=1, repo_url="https://github.com/org/repo1", repo_name="repo1", status="completed", runs=1)
    job2 = AnalysisJobModel(id=2, repo_url="https://github.com/org/repo2", repo_name="repo2", status="completed", runs=2)
    dash_html = dashboard_view(current_user=mock_user, billing_status=billing, past_jobs=[job1, job2])

    # 2. Settings
    settings_html = settings_view(
        current_user=mock_user,
        billing_status=billing,
        pricing_details={"unit_amount": 1000, "currency": "usd"},
    )

    # 3. Progress (done)
    job_done = {
        "id": 10,
        "repo_url": "https://github.com/org/repo1",
        "repo_name": "repo1",
        "status": "completed",
        "total_files": 42,
    }
    prog_html = progress_view(job=job_done, current_user=mock_user)

    # 4. Report overview
    md = """# Architectural Reverse-Engineering Report: `repo1`
*Synthesized at: 2026-10-24T00:00:00Z*

## 1. Executive Architecture Overview
- **Primary Language**: `Python`
- **Total Analyzed Files**: `25`
- **Domain Categories**: `3`
- **Entry Point Files**: `app.py`
- **Circular Dependency Components**: `0` files
- **Isolated / Support Files**: `2` files

### Domain Distribution
| Domain Category | File Count | Percentage |
| :--- | :--- | :--- |
| `core` | 15 | 60.0% |
| `api` | 8 | 32.0% |
| `utils` | 2 | 8.0% |

## 2. Build Order & Confidence Scoring
High confidence

## 3. Step-by-Step Architectural Milestones
### Milestone 1: Foundation
Foundational utilities.
- Included files: `app/util.py`
- Dominant domain: `utils`

### Milestone 2: Core Domain
Core business logic.
- Included files: `app/core.py`
- Dominant domain: `core`
"""
    graph_data = {
        "nodes": [
            {"id": "app/util.py", "path": "app/util.py", "tier": 1, "domain": "core", "confidence": "high"},
            {"id": "app/core.py", "path": "app/core.py", "tier": 2, "domain": "core", "confidence": "high"},
        ],
        "edges": [],
        "confidence_summary": {"high_pct": 100, "low_pct": 0, "low_count": 0, "history_available": True},
    }
    rep_html = report_view(
        job={"id": 10, "repo_name": "repo1", "repo_url": "https://github.com/org/repo1"},
        raw_markdown=md,
        graph_data=graph_data,
        quiz_data=None,
        current_user=mock_user,
    )

    return [
        ("progress (done)", prog_html),
        ("report overview", rep_html),
        ("settings", settings_html),
        ("dashboard", dash_html),
    ]


JS_INSPECT_GRIDS = """
() => {
    const results = [];
    const all = document.querySelectorAll('*');
    for (const el of all) {
        if (el.offsetParent === null && el.offsetWidth === 0 && el.offsetHeight === 0) continue;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') continue;

        const cls = (el.className && typeof el.className === 'string') ? el.className.toLowerCase() : '';
        const isGrid = style.display === 'grid';
        const hasStatKpi = cls.includes('stat') || cls.includes('kpi');

        if (isGrid || hasStatKpi) {
            const children = Array.from(el.children).filter(c => {
                const cStyle = window.getComputedStyle(c);
                return cStyle.display !== 'none' && c.offsetHeight > 0 && c.offsetWidth > 0;
            });
            if (children.length > 1) {
                const rows = [];
                let currentRowTop = null;
                let currentCount = 0;

                const sortedChildren = children.slice().sort((a, b) => {
                    const rA = a.getBoundingClientRect();
                    const rB = b.getBoundingClientRect();
                    if (Math.abs(rA.top - rB.top) > 4) return rA.top - rB.top;
                    return rA.left - rB.left;
                });

                for (const child of sortedChildren) {
                    const top = Math.round(child.getBoundingClientRect().top);
                    if (currentRowTop === null || Math.abs(top - currentRowTop) > 4) {
                        if (currentRowTop !== null) {
                            rows.push(currentCount);
                        }
                        currentRowTop = top;
                        currentCount = 1;
                    } else {
                        currentCount++;
                    }
                }
                if (currentCount > 0) {
                    rows.push(currentCount);
                }

                const sel = el.id ? '#' + el.id : (el.className ? '.' + el.className.trim().split(/\\s+/).join('.') : el.tagName.toLowerCase());
                const isOrphaned = rows.length > 1 && rows[rows.length - 1] < rows[0];
                results.push({
                    selector: sel,
                    isGrid: isGrid,
                    rows: rows,
                    orphaned: isOrphaned
                });
            }
        }
    }
    return results;
}
"""


@pytest.mark.parametrize("viewport_width", [390, 768])
def test_no_orphan_grids(viewport_width, test_pages_html):
    """
    Part F Playwright test:
    For progress (done), report overview, settings, dashboard at 390px and 768px:
    find every element with display:grid or class containing "stat" / "kpi",
    count cards per row by getBoundingClientRect().top,
    and fail if the last row has fewer cards than the previous rows (except for single row).
    """
    failures = []
    summary_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": viewport_width, "height": 844})

        for page_name, html_content in test_pages_html:
            page.set_content(html_content)
            grids = page.evaluate(JS_INSPECT_GRIDS)

            for g in grids:
                summary_rows.append((page_name, viewport_width, g["selector"], str(g["rows"]), "FAIL" if g["orphaned"] else "PASS"))
                if g["orphaned"]:
                    failures.append(
                        f"Page '{page_name}' at {viewport_width}px has orphaned cards in {g['selector']}: rows={g['rows']}"
                    )

        browser.close()

    # Print markdown table for easy verification
    print(f"\n| Page | Viewport | Selector | Cards Per Row | Status |")
    print(f"| :--- | :--- | :--- | :--- | :--- |")
    for r in summary_rows:
        print(f"| {r[0]} | {r[1]}px | `{r[2]}` | {r[3]} | **{r[4]}** |")

    assert len(failures) == 0, "\n".join(failures)
