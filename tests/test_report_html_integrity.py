import collections
import re
import pytest

from app.sequence.schema import (
    RepoConfidenceSummary,
    ScoredFileEntry,
    ScoredOrderingResult,
)
from app.parser.schema import FileNode
from app.segmentation.schema import SegmentationResult
from app.sequence.narration_engine import NarrationEngine
from app.synthesis.engine import SynthesisEngine
from app.formatters.markdown_formatter import MarkdownReportFormatter
from app.formatters.quiz_formatter import QuizFormatter
from app.ui.components import report_view


@pytest.fixture
def four_milestone_fixture_report():
    summary = RepoConfidenceSummary(
        high_pct=100.0,
        medium_pct=0.0,
        low_pct=0.0,
        history_available=True,
    )
    scored_files = [
        ScoredFileEntry(path="app/core.py", confidence="high", confidence_reason="verified", tier_index=0),
        ScoredFileEntry(path="app/api.py", confidence="high", confidence_reason="verified", tier_index=1),
        ScoredFileEntry(path="app/db.py", confidence="high", confidence_reason="verified", tier_index=2),
        ScoredFileEntry(path="tests/test_core.py", confidence="high", confidence_reason="verified", tier_index=3),
    ]
    ordering = ScoredOrderingResult(
        files=scored_files,
        repo_confidence_summary=summary,
        isolated_files=[],
        cyclic_files=[],
    )

    engine = NarrationEngine()
    narration = engine.generate_narration(ordering, None)
    synthesis_engine = SynthesisEngine()
    seg_res = SegmentationResult(domain_counts={"core": 3, "tests": 1})
    parsed_files = [
        FileNode(path="app/core.py", language="python", exports=["CoreClass"]),
        FileNode(path="app/api.py", language="python", exports=["api_router"]),
        FileNode(path="app/db.py", language="python", exports=["db_session"]),
        FileNode(path="tests/test_core.py", language="python", exports=["test_run"]),
    ]
    synth_report = synthesis_engine.synthesize(
        repo_name="guided-repo",
        segmentation_result=seg_res,
        narration_result=narration,
        parsed_files=parsed_files,
    )
    markdown_report = MarkdownReportFormatter().format_report(synth_report)
    quiz_data = QuizFormatter().generate_quiz(synth_report)

    job = {
        "id": 42,
        "repo_name": "guided-repo",
        "repo_url": "https://github.com/example/guided-repo",
    }

    html = report_view(
        job=job,
        raw_markdown=markdown_report,
        graph_data={"nodes": [], "edges": []},
        quiz_data=quiz_data,
    )
    return html


def test_report_html_id_uniqueness_4_milestones(four_milestone_fixture_report):
    """
    Part C requirement:
    In the 4-milestone fixture report, assert all element IDs are strictly unique:
    len(ids) == len(set(ids)).
    """
    html = four_milestone_fixture_report
    ids = re.findall(r'(?<![-a-zA-Z0-9])id=["\']([^"\']+)["\']', html)
    c = collections.Counter(ids)
    dupes = {k: v for k, v in c.items() if v > 1}

    assert len(dupes) == 0, f"Found duplicated element IDs: {dupes}"
    assert len(ids) == len(set(ids)), f"Expected len(ids) == len(set(ids)), but got {len(ids)} total and {len(set(ids))} unique"


def test_quiz_tab_and_milestone_quiz_playwright(tmp_path, four_milestone_fixture_report):
    """
    Part C Playwright test:
    Click an option, press Check in both places (milestone pane and Quiz tab),
    and verify the score appears in the right place without cross-contamination.
    """
    from playwright.sync_api import sync_playwright

    html = four_milestone_fixture_report
    html_file = tmp_path / "report_integrity_test.html"
    html_file.write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(html_file.as_uri())

        # Switch to Milestones tab so milestone panes become visible
        page.locator("#tab-btn-milestones").click()

        # 1. In Milestone 1 pane, select an option on Question 1
        m1_radio = page.locator('input[name="m_quiz_1_1"]').first
        m1_radio.check()
        assert m1_radio.is_checked()

        # Quiz tab radio for question 1 should remain unchecked
        quiztab_radio = page.locator('input[name="quiztab-m_quiz_1_1"]').first
        assert not quiztab_radio.is_checked()

        # Score banners initially hidden in both places
        m1_banner = page.locator("#quiz-score-banner-1")
        quiztab_banner = page.locator("#quiztab-quiz-score-banner-1")
        assert not m1_banner.is_visible()
        assert not quiztab_banner.is_visible()

        # Click "Check answers" in milestone 1 pane
        page.locator("#btn-check-quiz-1").click()

        # Milestone 1 banner is now visible with score
        assert m1_banner.is_visible()
        m1_score_text = page.locator("#quiz-score-text-1").inner_text()
        assert "correct" in m1_score_text

        # Quiz tab banner MUST STILL BE HIDDEN
        assert not quiztab_banner.is_visible()

        # 2. Switch to Quiz tab
        page.locator("#tab-btn-quiz").click()

        # In Quiz tab for Milestone 1, check an option and click Check
        quiztab_radio.check()
        assert quiztab_radio.is_checked()

        page.locator("#quiztab-btn-check-quiz-1").click()

        # Now Quiz tab banner is also visible with its own score
        assert quiztab_banner.is_visible()
        quiztab_score_text = page.locator("#quiztab-quiz-score-text-1").inner_text()
        assert "correct" in quiztab_score_text

        # 3. Retry quiz in quiz tab: resets quiz tab banner
        page.locator("#quiztab-btn-retry-quiz-1").click()
        assert not quiztab_banner.is_visible()

        # Switch back to Milestones tab: milestone 1 banner is still visible!
        page.locator("#tab-btn-milestones").click()
        assert m1_banner.is_visible()

        # Retry in milestone 1 pane: resets m1 banner
        page.locator("#btn-retry-quiz-1").click()
        assert not m1_banner.is_visible()

        browser.close()
