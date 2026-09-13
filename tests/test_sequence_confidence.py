"""Unit tests for Layer 6 (Stage C) Confidence Scoring Engine."""

import pytest
from app.models.history import CommitHistoryResult, FirstAppearance
from app.sequence.confidence_scoring import ConfidenceScoringEngine
from app.sequence.schema import (
    FileOrderEntry,
    RefinedOrderingResult,
    RefinedTier,
)


def test_high_confidence_topology_and_history():
    """
    Acceptance Criteria 1:
    A file ordered purely by topology with verified history tie-break is 'high' confidence.
    """
    refined = RefinedOrderingResult(
        tiers=[
            RefinedTier(
                tier_index=0,
                ordered_files=[
                    FileOrderEntry(path="a.py", tie_break_method="none"),
                    FileOrderEntry(path="b.py", tie_break_method="history"),
                ],
            )
        ]
    )

    engine = ConfidenceScoringEngine()
    result = engine.compute_confidence_scores(refined)

    assert len(result.files) == 2
    assert result.files[0].confidence == "high"
    assert result.files[0].confidence_reason == "topology (hard dependency fact)"

    assert result.files[1].confidence == "high"
    assert result.files[1].confidence_reason == "topology + verified history"

    assert result.repo_confidence_summary.high_pct == 100.0
    assert result.repo_confidence_summary.medium_pct == 0.0
    assert result.repo_confidence_summary.low_pct == 0.0


def test_low_confidence_cycle_vs_isolated():
    """
    Acceptance Criteria 2:
    A file in a detected cycle is 'low' confidence with a clear stated reason,
    distinct from an isolated file's 'low' confidence reason.
    """
    refined = RefinedOrderingResult(
        tiers=[
            RefinedTier(
                tier_index=0,
                ordered_files=[
                    FileOrderEntry(path="cyc1.py", tie_break_method="none"),
                    FileOrderEntry(path="cyc2.py", tie_break_method="none"),
                ],
                is_cyclic_cluster=True,
            )
        ],
        isolated_files=["standalone.py"],
        cyclic_files=["cyc1.py", "cyc2.py"],
    )

    engine = ConfidenceScoringEngine()
    result = engine.compute_confidence_scores(refined)

    file_map = {f.path: f for f in result.files}

    # Cycle files -> low confidence with cycle reason
    assert file_map["cyc1.py"].confidence == "low"
    assert file_map["cyc1.py"].confidence_reason == "cyclic cluster (circular dependency)"

    assert file_map["cyc2.py"].confidence == "low"
    assert file_map["cyc2.py"].confidence_reason == "cyclic cluster (circular dependency)"

    # Isolated file -> low confidence with isolated reason
    assert file_map["standalone.py"].confidence == "low"
    assert file_map["standalone.py"].confidence_reason == "isolated, no internal dependency signal"

    # Reasons are distinct!
    assert file_map["cyc1.py"].confidence_reason != file_map["standalone.py"].confidence_reason


def test_medium_confidence_llm_and_heuristic():
    """
    Acceptance Criteria 3:
    A file tie-broken by the LLM is 'medium' confidence, naming the exact method in the reason.
    """
    refined = RefinedOrderingResult(
        tiers=[
            RefinedTier(
                tier_index=0,
                ordered_files=[
                    FileOrderEntry(path="heur.py", tie_break_method="heuristic"),
                    FileOrderEntry(path="llm_choice.py", tie_break_method="llm", reasoning="LLM choice rationale"),
                ],
            )
        ]
    )

    engine = ConfidenceScoringEngine()
    result = engine.compute_confidence_scores(refined)

    file_map = {f.path: f for f in result.files}

    assert file_map["heur.py"].confidence == "medium"
    assert file_map["heur.py"].confidence_reason == "topology + domain heuristic tie-break"

    assert file_map["llm_choice.py"].confidence == "medium"
    assert file_map["llm_choice.py"].confidence_reason == "topology + LLM tie-break"
    assert file_map["llm_choice.py"].reasoning == "LLM choice rationale"


def test_zip_upload_no_history_repo_summary():
    """
    Acceptance Criteria 4:
    A repo with history_available: False (zip-upload case) produces a repo-level summary
    that honestly reflects lower overall confidence, not a summary that looks like a rich history repo.
    """
    refined = RefinedOrderingResult(
        tiers=[
            RefinedTier(
                tier_index=0,
                ordered_files=[
                    FileOrderEntry(path="file1.py", tie_break_method="unresolved"),
                    FileOrderEntry(path="file2.py", tie_break_method="heuristic"),
                ],
            )
        ]
    )

    no_history = CommitHistoryResult(
        history_available=False,
        history_confidence="reduced",
        commit_count_total=0,
    )

    engine = ConfidenceScoringEngine()
    result = engine.compute_confidence_scores(refined, commit_history=no_history)

    assert result.repo_confidence_summary.history_available is False
    assert result.repo_confidence_summary.low_pct > 0.0
    assert result.repo_confidence_summary.high_pct == 0.0


def test_all_files_have_specific_reasons():
    """
    Acceptance Criteria 5:
    Every file has a specific, human-readable confidence reason — no generic reasons without explanation.
    """
    refined = RefinedOrderingResult(
        tiers=[
            RefinedTier(
                tier_index=0,
                ordered_files=[
                    FileOrderEntry(path="a.py", tie_break_method="none"),
                    FileOrderEntry(path="b.py", tie_break_method="history"),
                    FileOrderEntry(path="c.py", tie_break_method="heuristic"),
                    FileOrderEntry(path="d.py", tie_break_method="llm"),
                    FileOrderEntry(path="e.py", tie_break_method="unresolved"),
                ],
            )
        ],
        isolated_files=["iso.py"],
    )

    engine = ConfidenceScoringEngine()
    result = engine.compute_confidence_scores(refined)

    for entry in result.files:
        assert entry.confidence_reason is not None
        assert len(entry.confidence_reason.strip()) > 5
        assert "confidence" not in entry.confidence_reason  # Non-generic specific description
