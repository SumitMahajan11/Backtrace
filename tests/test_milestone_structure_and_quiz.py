"""Tests for Milestone Structure, Deduplication, and Quiz Non-Guessability.

Covers Part A (ordering and titles), Part B (card deduplication), and Part C (quiz).
"""

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
def repo_fixture_4_core_3_test():
    """Fixture of 4 core files and 3 test files, with test files originally interspersed."""
    summary = RepoConfidenceSummary(
        high_pct=100.0,
        medium_pct=0.0,
        low_pct=0.0,
        history_available=True,
    )
    # Notice test files are interspersed across tiers 0, 1, 2
    scored_files = [
        ScoredFileEntry(path="app/models.py", confidence="high", confidence_reason="verified", tier_index=0),
        ScoredFileEntry(path="tests/test_models.py", confidence="high", confidence_reason="verified", tier_index=1),
        ScoredFileEntry(path="app/utils.py", confidence="high", confidence_reason="verified", tier_index=2),
        ScoredFileEntry(path="tests/test_service.py", confidence="high", confidence_reason="verified", tier_index=3),
        ScoredFileEntry(path="app/service.py", confidence="high", confidence_reason="verified", tier_index=4),
        ScoredFileEntry(path="test_main.py", confidence="high", confidence_reason="verified", tier_index=5),
        ScoredFileEntry(path="main.py", confidence="high", confidence_reason="verified", tier_index=6),
    ]
    return ScoredOrderingResult(
        files=scored_files,
        repo_confidence_summary=summary,
        isolated_files=[],
        cyclic_files=[],
    )


def test_part_a_ordering_titles_and_numbering(repo_fixture_4_core_3_test):
    """Part A requirements:

    - Milestones with only test files go into test_track, ordered after all core milestones.
    - Unique titles in format 'Understand {folder_or_file_name}'.
    - Core milestones numbered 1..N. Test track labeled 'Test files', numbered T1..Tn.
    - No 'Milestone 0' or 'Tier 0' in user text; starts at Milestone 1.
    - main.py appears in core track before any test milestone.
    - Fixture with 4 core files and 3 test files asserts unique titles, no test before core, 1..N.
    """
    engine = NarrationEngine()
    narration = engine.generate_narration(repo_fixture_4_core_3_test, None)

    # 1. Assert separate core steps and test_track
    assert len(narration.steps) == 4, f"Expected 4 core milestones, got {len(narration.steps)}"
    assert len(narration.test_track) == 3, f"Expected 3 test milestones, got {len(narration.test_track)}"

    # 2. Assert no test milestone appears before any core milestone
    all_core_files = [f for s in narration.steps for f in s.files]
    all_test_files = [f for s in narration.test_track for f in s.files]

    for f in all_core_files:
        assert not f.startswith("tests/") and not f.startswith("test_")

    for f in all_test_files:
        assert f.startswith("tests/") or f.startswith("test_")

    # 3. Assert main.py is in the core track
    assert "main.py" in all_core_files
    assert "main.py" not in all_test_files

    # 4. Assert titles are unique and match format 'Understand ...'
    all_titles = [s.title for s in narration.steps] + [s.title for s in narration.test_track]
    assert len(all_titles) == len(set(all_titles)), f"Titles are not unique: {all_titles}"
    for t in all_titles:
        assert t.startswith("Understand "), f"Title does not start with 'Understand ': {t}"

    # 5. Assert numbering is 1..N with no 0, and test track is T1..Tn
    core_step_numbers = [s.step_number for s in narration.steps]
    assert core_step_numbers == [1, 2, 3, 4]
    assert 0 not in core_step_numbers

    core_display_ids = [s.display_id for s in narration.steps]
    assert core_display_ids == ["1", "2", "3", "4"]

    test_display_ids = [s.display_id for s in narration.test_track]
    assert test_display_ids == ["T1", "T2", "T3"]
    for s in narration.test_track:
        assert s.track_label == "Test files"

    # 6. Synthesize report and check confidence table
    synthesis_engine = SynthesisEngine()
    seg_res = SegmentationResult(
        domain_counts={"core": 4, "tests": 3},
        method_counts={"convention": 7},
    )
    parsed_files = [
        FileNode(path="app/models.py", language="python", exports=["User"]),
        FileNode(path="app/utils.py", language="python", exports=["format_date"]),
        FileNode(path="app/service.py", language="python", exports=["login"]),
        FileNode(path="main.py", language="python", exports=["run"]),
        FileNode(path="tests/test_models.py", language="python", exports=["test_user"]),
        FileNode(path="tests/test_service.py", language="python", exports=["test_login"]),
        FileNode(path="test_main.py", language="python", exports=["test_run"]),
    ]
    synth_report = synthesis_engine.synthesize(
        repo_name="fixture-repo",
        segmentation_result=seg_res,
        narration_result=narration,
        parsed_files=parsed_files,
    )

    conf_table = synth_report.confidence_disclosure
    assert "Milestone 0" not in conf_table
    assert "Tier 0" not in conf_table
    assert "Milestone 1" in conf_table
    assert "Test files T1" in conf_table


def test_part_b_card_deduplication():
    """Part B requirements:

    - The 'Role' paragraph appears once, in the card header only.
    - Files listed twice (chips and tabs). Keep the tabs only.
    """
    engine = NarrationEngine()
    synthesis_engine = SynthesisEngine()
    multi_file_scored = ScoredOrderingResult(
        files=[
            ScoredFileEntry(path="app/models.py", confidence="high", confidence_reason="verified", tier_index=0),
            ScoredFileEntry(path="app/base.py", confidence="high", confidence_reason="verified", tier_index=0),
            ScoredFileEntry(path="app/service.py", confidence="high", confidence_reason="verified", tier_index=1),
        ],
        repo_confidence_summary=RepoConfidenceSummary(
            high_pct=100.0, medium_pct=0.0, low_pct=0.0, history_available=True
        ),
        isolated_files=[],
        cyclic_files=[],
    )
    narration = engine.generate_narration(multi_file_scored, None)
    seg_res = SegmentationResult(domain_counts={"core": 3})
    parsed_files = [
        FileNode(path="app/models.py", language="python", exports=["User"]),
        FileNode(path="app/base.py", language="python", exports=["BaseModel"]),
        FileNode(path="app/service.py", language="python", exports=["login"]),
    ]
    synth_report = synthesis_engine.synthesize(
        repo_name="fixture-repo",
        segmentation_result=seg_res,
        narration_result=narration,
        parsed_files=parsed_files,
    )

    markdown_report = MarkdownReportFormatter().format_report(synth_report)
    job_mock = {
        "id": 1,
        "repo_name": "fixture-repo",
        "repo_url": "https://github.com/example/fixture-repo",
    }

    html = report_view(
        job=job_mock,
        raw_markdown=markdown_report,
        graph_data={"nodes": [], "edges": []},
        quiz_data=None,
    )

    milestones_sec = html[html.find('id="section-milestones"'):html.find('id="section-quiz"')]

    # 1. Assert 'Role' paragraph appears in card header (.milestone-role) only once
    assert 'class="milestone-role"' in milestones_sec
    assert milestones_sec.count('class="milestone-role"') == 2  # exactly 1 per milestone card

    # 2. Assert Included Files chips tray is removed from milestone cards, while tabs are kept
    assert 'class="milestone-file-chip"' not in milestones_sec
    assert "milestone-files-chips" not in milestones_sec
    assert 'class="guess-file-tab-btn' in milestones_sec
    assert "read-file-tabs" in milestones_sec

    # 3. Assert no Milestone 0 or Tier 0 in user text
    assert "Milestone 0" not in milestones_sec
    assert "Tier 0" not in milestones_sec
    assert "Milestone 1" in milestones_sec


def test_part_c_quiz_nonguessability_and_different_options(repo_fixture_4_core_3_test):
    """Part C requirements:

    1. Distractors (wrong options) must come from OTHER milestones' real content, not copies of the same set of options.
       Each question has 4 options. The options differ per question.
    2. The question text must not contain the milestone title or the correct file name.
    3. Shuffle option order with a seed based on question id so it is stable.
    4. Test: for 7 generated questions, assert no two questions have identical option sets
       and no question text contains the correct answer string.
    """
    engine = NarrationEngine()
    narration = engine.generate_narration(repo_fixture_4_core_3_test, None)
    synthesis_engine = SynthesisEngine()
    seg_res = SegmentationResult(domain_counts={"core": 4, "tests": 3})
    parsed_files = [
        FileNode(path="app/models.py", language="python", exports=["User"]),
        FileNode(path="app/utils.py", language="python", exports=["format_date"]),
        FileNode(path="app/service.py", language="python", exports=["login"]),
        FileNode(path="main.py", language="python", exports=["run"]),
        FileNode(path="tests/test_models.py", language="python", exports=["test_user"]),
        FileNode(path="tests/test_service.py", language="python", exports=["test_login"]),
        FileNode(path="test_main.py", language="python", exports=["test_run"]),
    ]
    synth_report = synthesis_engine.synthesize(
        repo_name="fixture-repo",
        segmentation_result=seg_res,
        narration_result=narration,
        parsed_files=parsed_files,
    )

    quiz_formatter = QuizFormatter()
    quiz_res_1 = quiz_formatter.generate_quiz(synth_report)
    quiz_res_2 = quiz_formatter.generate_quiz(synth_report)

    questions = quiz_res_1["questions"]
    assert len(questions) == 7, f"Expected 7 questions for 7 milestones, got {len(questions)}"

    # 1. Stable shuffle assertion across multiple invocations
    for q1, q2 in zip(questions, quiz_res_2["questions"]):
        assert q1["options"] == q2["options"]
        assert q1["correct_option_index"] == q2["correct_option_index"]

    # 2. Assert each question has 4 options
    for q in questions:
        assert len(q["options"]) == 4, f"Question {q['id']} does not have 4 options"
        assert len(set(q["options"])) == 4, f"Question {q['id']} contains duplicate options"

    # 3. Assert no two questions have identical option sets
    option_sets = [frozenset(q["options"]) for q in questions]
    assert len(set(option_sets)) == 7, "Some questions have identical option sets"

    # 4. Assert question text does NOT contain milestone title, correct file name, or correct answer string
    all_milestones = synth_report.milestones + synth_report.test_track
    for q, m in zip(questions, all_milestones):
        correct_answer_str = q["options"][q["correct_option_index"]]
        q_text = q["question"]

        # No milestone title in question text
        assert m.title not in q_text, f"Question text contains milestone title '{m.title}': {q_text}"

        # No correct file name in question text
        for f in m.files:
            file_name = f.replace("\\", "/").split("/")[-1]
            assert f not in q_text, f"Question text contains file path '{f}': {q_text}"
            assert file_name not in q_text, f"Question text contains file name '{file_name}': {q_text}"

        # No correct answer string in question text
        assert correct_answer_str not in q_text, f"Question text contains correct answer: {q_text}"
