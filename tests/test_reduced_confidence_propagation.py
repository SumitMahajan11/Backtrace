"""Unit test for reduced history confidence detection and end-to-end downstream propagation.

Verifies:
1. Mismatch between commit_count_total and commit_count_processed forces history_confidence="reduced".
2. Stage B's constrained tie-breaker guard skips history tie-breaking when confidence is "reduced".
3. Stage C's confidence scoring labels affected files as "low" with explicit reason:
   'reduced history confidence (squashed or rebased commits)'.
"""

import pytest
from app.models.history import CommitHistoryResult, CommitSummary, FirstAppearance
from app.sequence.schema import BaselineOrderingResult, NodeMetadata, Tier
from app.services.history_extractor import HistoryExtractorService
from app.sequence.constrained_tie_breaking import ConstrainedTieBreakerEngine
from app.sequence.confidence_scoring import ConfidenceScoringEngine


def test_forced_partial_walk_propagation():
    print("\n" + "=" * 70)
    print("RUNNING FORCED PARTIAL-WALK REDUCED CONFIDENCE VERIFICATION")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # Step 2a: Force partial-walk mismatch and assert history_confidence="reduced"
    # -------------------------------------------------------------------------
    service = HistoryExtractorService()
    forced_total_commits = 10
    forced_processed_commits = 3

    # Direct evaluation via service's confidence evaluator
    confidence = service._evaluate_confidence(
        total_commit_count=forced_total_commits,
        unique_paths=10,
        processed_count=forced_processed_commits,
        max_commits=None,
        is_shallow=False,
    )

    history_result = CommitHistoryResult(
        history_available=True,
        commits=[
            CommitSummary(hash=f"hash_{i}", author="Dev", timestamp=f"202{i}-01-01T00:00:00Z", message=f"commit {i}")
            for i in range(forced_processed_commits)
        ],
        file_first_appearance={
            "app/core.py": FirstAppearance(commit_hash="hash_0", timestamp="2020-01-01T00:00:00Z"),
            "app/utils.py": FirstAppearance(commit_hash="hash_1", timestamp="2021-01-01T00:00:00Z"),
        },
        history_confidence=confidence,
        commit_count_processed=forced_processed_commits,
        commit_count_total=forced_total_commits,
    )

    print(f"[Step 2a] Forced partial-walk mismatch:")
    print(f"  commit_count_total:     {history_result.commit_count_total}")
    print(f"  commit_count_processed: {history_result.commit_count_processed}")
    print(f"  history_confidence:     '{history_result.history_confidence}'")
    assert history_result.history_confidence == "reduced"

    # -------------------------------------------------------------------------
    # Step 2b: Stage B skips history tie-breaking when confidence is "reduced"
    # -------------------------------------------------------------------------
    tier_0_files = ["app/core.py", "app/utils.py"]
    baseline = BaselineOrderingResult(
        tiers=[Tier(tier_index=0, files=tier_0_files)],
        node_metadata={
            "app/core.py": NodeMetadata(path="app/core.py", domain="core"),
            "app/utils.py": NodeMetadata(path="app/utils.py", domain="core"),
        },
    )

    tie_breaker = ConstrainedTieBreakerEngine()

    # If confidence were HIGH, these two files with distinct timestamps WOULD be history-ordered:
    high_history = history_result.model_copy(update={"history_confidence": "high"})
    refined_high = tie_breaker.refine_baseline_order(baseline, commit_history=high_history)
    high_methods = [entry.tie_break_method for entry in refined_high.tiers[0].ordered_files]

    # With REDUCED confidence, Stage B must skip history tie-breaking:
    refined_reduced = tie_breaker.refine_baseline_order(baseline, commit_history=history_result)
    reduced_entries = refined_reduced.tiers[0].ordered_files
    reduced_methods = [entry.tie_break_method for entry in reduced_entries]

    print(f"\n[Step 2b] Stage B Tier 0 Tie-Breaking Guard Verification:")
    print(f"  Input Tier 0 files (distinct timestamps): {tier_0_files}")
    print(f"  Under 'high' confidence tie-break methods:    {high_methods} (proves history ordering works when valid)")
    print(f"  Under 'reduced' confidence tie-break methods: {reduced_methods} (proves history guard SKIPPED history)")

    # Assert that history tie-breaking was skipped
    for entry in reduced_entries:
        assert entry.tie_break_method != "history", (
            f"Expected history tie-breaking to be skipped, but {entry.path} had method {entry.tie_break_method}"
        )
        assert entry.tie_break_method in ("heuristic", "unresolved")

    # -------------------------------------------------------------------------
    # Step 2c: Stage C labels affected files "low" with specific reason string
    # -------------------------------------------------------------------------
    scorer = ConfidenceScoringEngine()
    scored_result = scorer.compute_confidence_scores(refined_reduced, commit_history=history_result)

    print(f"\n[Step 2c] Stage C File Confidence Scoring Verification:")
    for f in scored_result.files:
        print(f"  File: {f.path}")
        print(f"    confidence:        '{f.confidence}'")
        print(f"    confidence_reason: '{f.confidence_reason}'")
        print(f"    tie_break_method:  '{f.tie_break_method}'")

        assert f.confidence == "low", f"Expected 'low' confidence, got '{f.confidence}'"
        expected_reason = "reduced history confidence (squashed or rebased commits)"
        assert f.confidence_reason == expected_reason, (
            f"Expected specific reason '{expected_reason}', got '{f.confidence_reason}'"
        )

    print("=" * 70 + "\n")


if __name__ == "__main__":
    test_forced_partial_walk_propagation()
