"""Tests for Guided Flow Milestones, Progress Rail, Popovers, and Milestone Quiz.

Covers:
1. Progress Rail Layout (Desktop vertical rail, Mobile scroll strip CSS).
2. Single open milestone (only the first not-done milestone open initially).
3. "Start here" and "Next milestone" buttons.
4. Status labels ('Not started', 'In progress', 'Done') and 8px gap.
5. 'Test files' separate rail section.
6. Click-to-open (i) info popover with button and aria-expanded.
7. 60vh single scroll code pane, line numbers, and self-hosted highlight.js (no CDN).
8. Quiz flow: 'Check your understanding' with 3 questions, 44px radio rows, score format,
   score persistence endpoint, and old Quiz tab route compatibility.
9. XSS sanitization across milestone text and quiz data.
"""

import json
import os
import re
import html
import pytest
from fastapi.testclient import TestClient

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
from app.main import app
from app.api.dependencies import get_current_user, get_db
from app.models.db import AnalysisJobModel, MilestoneAttemptModel, UserModel
from app.db.session import init_db, get_db_session


@pytest.fixture
def guided_repo_fixture():
    summary = RepoConfidenceSummary(
        high_pct=100.0,
        medium_pct=0.0,
        low_pct=0.0,
        history_available=True,
    )
    scored_files = [
        ScoredFileEntry(path="app/core.py", confidence="high", confidence_reason="verified", tier_index=0),
        ScoredFileEntry(path="app/api.py", confidence="high", confidence_reason="verified", tier_index=1),
        ScoredFileEntry(path="tests/test_core.py", confidence="high", confidence_reason="verified", tier_index=2),
    ]
    return ScoredOrderingResult(
        files=scored_files,
        repo_confidence_summary=summary,
        isolated_files=[],
        cyclic_files=[],
    )


def build_test_report_html(guided_repo_fixture, attempts_override=None, lazy_milestones=False):
    engine = NarrationEngine()
    narration = engine.generate_narration(guided_repo_fixture, None)
    synthesis_engine = SynthesisEngine()
    seg_res = SegmentationResult(domain_counts={"core": 2, "tests": 1})
    parsed_files = [
        FileNode(path="app/core.py", language="python", exports=["CoreClass"]),
        FileNode(path="app/api.py", language="python", exports=["api_router"]),
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

    job_mock = {
        "id": 42,
        "repo_name": "guided-repo",
        "repo_url": "https://github.com/example/guided-repo",
    }

    attempts_dict = {}
    if attempts_override:
        if isinstance(attempts_override, dict):
            attempts_dict = attempts_override
        elif isinstance(attempts_override, list):
            for a in attempts_override:
                t = a.get("milestone_tier", 1) if isinstance(a, dict) else getattr(a, "milestone_tier", 1)
                attempts_dict[t] = a

    return report_view(
        job=job_mock,
        raw_markdown=markdown_report,
        graph_data={"nodes": [], "edges": []},
        quiz_data=quiz_data,
        attempts_by_tier=attempts_dict,
        lazy_milestones=lazy_milestones,
    )


def test_progress_rail_layout_and_test_files_group(guided_repo_fixture):
    """1. Left progress rail (number, title, status icon) + Test milestones under separate rail heading."""
    rendered_html = build_test_report_html(guided_repo_fixture)

    # Rail container exists
    assert 'class="milestones-guided-flow"' in rendered_html
    assert 'class="milestone-progress-rail"' in rendered_html

    # Core milestones and separate 'Test files' heading
    assert 'Core Milestones' in rendered_html
    assert 'Test files' in rendered_html
    assert '<div class="rail-group-title"' in rendered_html

    # Rail items include display ID (1, 2, T1), title, and status
    assert '<span class="rail-item-num">1</span>' in rendered_html
    assert '<span class="rail-item-num">2</span>' in rendered_html
    assert '<span class="rail-item-num">T1</span>' in rendered_html

    # Status icon has 8px gap
    assert 'gap: 8px;' in rendered_html
    assert 'class="rail-status-item"' in rendered_html


def test_single_open_milestone_and_main_area_elements(guided_repo_fixture):
    """2. Only ONE milestone is open at a time (first not-done one).

    Main area shows: title, one-sentence goal, target-file tabs, practice mode switch, code pane.
    """
    rendered_html = build_test_report_html(guided_repo_fixture)

    # First milestone (tier 1) is open with display: block
    assert 'id="milestone-pane-1"' in rendered_html
    assert 'id="milestone-pane-2"' in rendered_html
    assert 'id="milestone-pane-3"' in rendered_html

    # Pane 1 is open (display: block;), panes 2 and 3 are closed (display: none;)
    assert 'id="milestone-pane-1" style="display: block;"' in rendered_html
    assert 'id="milestone-pane-2" style="display: none;"' in rendered_html
    assert 'id="milestone-pane-3" style="display: none;"' in rendered_html

    # Active class on open pane
    assert 'class="milestone-pane active" id="milestone-pane-1"' in rendered_html
    assert 'class="milestone-pane" id="milestone-pane-2"' in rendered_html

    # Main area components
    assert 'Goal:' in rendered_html
    # Mode switch 3 tabs: Read it, Fill the gaps, Try it
    assert 'Read it' in rendered_html
    assert 'Fill the gaps' in rendered_html
    assert 'Try it' in rendered_html
    assert 'id="mode-btn-read-1"' in rendered_html
    assert 'id="mode-btn-fill-1"' in rendered_html
    assert 'id="mode-btn-guess-1"' in rendered_html

    # Code pane container with 60vh
    assert 'class="code-pane-container"' in rendered_html or 'height: 60vh;' in rendered_html


def test_start_here_and_next_milestone_buttons(guided_repo_fixture):
    """3. 'Start here' on first not-done milestone. 'Next milestone' on done milestone."""
    # Scenario A: No milestones completed -> tier 1 has 'Start here'
    html_initial = build_test_report_html(guided_repo_fixture, attempts_override=[])
    assert 'id="btn-start-here-1"' in html_initial
    assert 'Start here' in html_initial
    # In initial state, next milestone button on tier 1 is hidden
    assert 'id="btn-next-milestone-1"' in html_initial
    assert 'id="btn-next-milestone-1" class="btn btn-sm btn-secondary btn-next-milestone" onclick="goToNextMilestone(1)" style="display: none;' in html_initial

    # Scenario B: Tier 1 completed (structurally_verified) -> tier 1 has 'Next milestone' visible, tier 2 is first not-done
    attempt_done_1 = {
        "milestone_tier": 1,
        "attempt_status": "structurally_verified",
        "grading_details_json": {"quiz_score": 3, "quiz_total": 3},
    }
    html_done_1 = build_test_report_html(guided_repo_fixture, attempts_override=[attempt_done_1])

    # Next milestone button is now visible on tier 1
    assert 'id="btn-next-milestone-1" class="btn btn-sm btn-secondary btn-next-milestone" onclick="goToNextMilestone(1)" style="display: inline-flex;' in html_done_1
    assert 'Next milestone' in html_done_1
    # Tier 2 is now first not-done, so it gets Start here visible
    assert 'id="btn-start-here-2" class="btn btn-sm btn-primary btn-start-here" onclick="startHereMilestone(2)" style="display: inline-flex;' in html_done_1
    # Tier 2 is now the active open pane
    assert 'class="milestone-pane active" id="milestone-pane-2" style="display: block;"' in html_done_1
    assert 'class="milestone-pane" id="milestone-pane-1" style="display: none;"' in html_done_1


def test_exact_statuses_and_gap_rule(guided_repo_fixture):
    """4. Statuses: Exactly Not started, In progress, Done.

    No jammed dot; icon with gap of 8px.
    """
    attempt_in_progress = {
        "milestone_tier": 1,
        "attempt_status": "in_progress",
    }
    attempt_done = {
        "milestone_tier": 2,
        "attempt_status": "structurally_verified",
    }
    rendered_html = build_test_report_html(
        guided_repo_fixture,
        attempts_override=[attempt_in_progress, attempt_done],
    )

    # Check status texts in rail
    assert "In progress" in rendered_html
    assert "Done" in rendered_html
    assert "Not started" in rendered_html

    # Ensure gap: 8px is styled
    with open("static/style.css", "r", encoding="utf-8") as f:
        css = f.read()
    assert ".rail-status-item" in css
    assert "gap: 8px;" in css


def test_info_icon_popover_touch_and_button():
    """6. The (i) info icons are click-to-open popovers using button element and aria-expanded."""
    with open("app/ui/components.py", "r", encoding="utf-8") as f:
        src = f.read()

    # Button element with aria-expanded="false" and click handler
    assert 'class="info-icon-btn"' in src
    assert 'aria-expanded="false"' in src
    assert 'onclick="toggleConfidencePopover(this, event)"' in src
    assert 'toggleConfidencePopover' in src

    # Verify no hover-only dependency in CSS
    assert '.tooltip-container:hover .confidence-tooltip' not in src


def test_code_pane_60vh_and_self_hosted_highlightjs():
    """7. Code pane height 60vh, single scroll area, line numbers, self-hosted highlight.js."""
    # Check self-hosted highlight.js files in static/
    assert os.path.exists("static/highlight.min.js"), "static/highlight.min.js missing!"
    assert os.path.exists("static/highlight.min.css"), "static/highlight.min.css missing!"
    assert os.path.getsize("static/highlight.min.js") > 50000, "highlight.min.js too small!"

    # Check components.py loads local files, not CDN
    with open("app/ui/components.py", "r", encoding="utf-8") as f:
        comps = f.read()
    assert 'src="/static/highlight.min.js"' in comps
    assert 'href="/static/highlight.min.css"' in comps
    assert 'cdnjs.cloudflare.com/ajax/libs/highlight.js' not in comps

    # Check 60vh single scroll styles in static/style.css
    with open("static/style.css", "r", encoding="utf-8") as f:
        css = f.read()
    assert "height: 60vh;" in css
    assert ".code-pane-container" in css
    assert ".code-line-table" in css
    assert ".code-line-num" in css


def test_quiz_flow_in_milestones_and_route_compatibility(guided_repo_fixture):
    """8. Quiz: moved into flow as 'Check your understanding', 3 questions, 44px rows, score display, retry button,

    and old Quiz tab route compatibility.
    """
    rendered_html = build_test_report_html(guided_repo_fixture)

    # 1. "Check your understanding" present
    assert "Check your understanding" in rendered_html
    assert 'class="milestone-quiz-card"' in rendered_html

    # 2. 3 questions per milestone
    assert 'data-question-idx="1"' in rendered_html
    assert 'data-question-idx="2"' in rendered_html
    assert 'data-question-idx="3"' in rendered_html

    # 3. Radio options have class .quiz-option-row
    assert 'class="quiz-option-row"' in rendered_html

    # Check min-height 44px in style.css
    with open("static/style.css", "r", encoding="utf-8") as f:
        css = f.read()
    assert ".quiz-option-row" in css
    assert "min-height: 44px;" in css

    # 4. Score container with 'of 3 correct' template and Retry button
    assert 'of 3 correct' in rendered_html
    assert 'Retry' in rendered_html
    assert 'Check answers' in rendered_html

    # 5. Old Quiz tab route working: section-quiz lists all quizzes
    assert 'id="section-quiz"' in rendered_html
    assert 'All Milestone Quizzes' in rendered_html


def test_quiz_score_persistence_api():
    """8 (continued). Persist quiz score through backend endpoint /attempts/{job_id}/{milestone_tier}/quiz."""
    init_db()
    user_id = 999
    with get_db_session() as session:
        user = session.query(UserModel).filter_by(id=user_id).first()
        if not user:
            user = UserModel(id=user_id, github_id=999999, github_username="persist_user", email="persist@example.com")
            session.add(user)
            session.flush()

        job = session.query(AnalysisJobModel).filter_by(id=999).first()
        if not job:
            job = AnalysisJobModel(
                id=999,
                user_id=user_id,
                repo_name="persist-repo",
                github_url="https://github.com/example/persist-repo",
                run_id="run-persist-999",
                status="completed",
                markdown_output="# Test",
            )
            session.add(job)
            session.commit()
        job_id = job.id

    mock_user = type("MockUser", (), {"id": user_id, "role": "user", "github_username": "persist_user"})()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    try:
        client = TestClient(app)
        resp = client.post(
            f"/attempts/{job_id}/1/quiz",
            json={"score": 2, "total": 3},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["quiz_score"] == 2
        assert data["quiz_total"] == 3
        assert data["score_text"] == "2 of 3 correct"
        assert data["grading_details"]["quiz_score"] == 2
        assert data["grading_details"]["quiz_total"] == 3

        # Verify attempt in DB
        with get_db_session() as session:
            attempt = session.query(MilestoneAttemptModel).filter_by(job_id=job_id, milestone_tier=1).first()
            assert attempt is not None
            details = json.loads(attempt.grading_details_json) if isinstance(attempt.grading_details_json, str) else attempt.grading_details_json
            assert details["quiz_score"] == 2
            assert details["quiz_total"] == 3
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_xss_sanitization_in_milestones_and_quiz():
    """Evidence requirement: XSS sanitization tests across milestone fields and quiz items."""
    xss_payload = "<script>alert('xss')</script><img src=x onerror=alert(1)>"

    # Narration with XSS payload
    narration_engine = NarrationEngine()
    scored = ScoredOrderingResult(
        files=[
            ScoredFileEntry(path="app/<script>alert(1)</script>.py", confidence="high", confidence_reason="verified", tier_index=0),
        ],
        repo_confidence_summary=RepoConfidenceSummary(high_pct=100.0, medium_pct=0.0, low_pct=0.0, history_available=True),
        isolated_files=[],
        cyclic_files=[],
    )
    narration = narration_engine.generate_narration(scored, None)
    # Inject malicious title and explanation
    narration.steps[0].title = f"Milestone {xss_payload}"
    narration.steps[0].pedagogical_explanation = f"Goal {xss_payload}"

    synth = SynthesisEngine().synthesize(
        repo_name="xss-repo",
        segmentation_result=SegmentationResult(domain_counts={"core": 1}),
        narration_result=narration,
        parsed_files=[FileNode(path="app/<script>alert(1)</script>.py", language="python", exports=[])],
    )
    md = MarkdownReportFormatter().format_report(synth)

    # Quiz with XSS in questions and options
    quiz = {
        "questions": [
            {
                "id": "q-xss",
                "tier": 1,
                "question": f"What is {xss_payload}?",
                "options": [f"Option {xss_payload}", "Safe 1", "Safe 2", "Safe 3"],
                "correct_option_index": 0,
                "explanation": f"Explanation {xss_payload}",
            }
        ]
    }

    job_mock = {"id": 999, "repo_name": "xss-repo", "repo_url": "https://github.com/example/xss"}
    rendered = report_view(job=job_mock, raw_markdown=md, graph_data={"nodes": [], "edges": []}, quiz_data=quiz)

    # Script tag MUST NOT appear unescaped in HTML
    assert "<script>alert('xss')</script>" not in rendered
    assert "<img src=x onerror=alert(1)>" not in rendered
    # Must be properly escaped
    assert ("&lt;script&gt;alert(" in rendered or "&lt;img src=x" in rendered)
