"""Reproducible verification script comparing pre-fix and post-fix Bug A and Bug B states.

Anyone can run this script to reproduce the exact counts against tests/fixtures/real_repos/flask:
    python scripts/reproduce_bug_ab_comparison.py
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parser.python_parser import PythonLanguageParser
from app.segmentation.engine import SegmentationEngine
from app.sequence.baseline_ordering import BaselineOrderingEngine
from app.sequence.confidence_scoring import ConfidenceScoringEngine
from app.sequence.constrained_tie_breaking import ConstrainedTieBreakerEngine
from app.sequence.schema import FileOrderEntry
from app.services.history_extractor import (
    CommitHistoryResult,
    FirstAppearance,
    HistoryExtractorService,
)


class PreFixTieBreakerEngine(ConstrainedTieBreakerEngine):
    """Reconstructs the pre-Bug-B Stage B tie breaker with the all-or-nothing timestamp guard."""

    def _refine_single_tier(
        self,
        tier_files: List[str],
        is_cyclic_cluster: bool,
        commit_history: Optional[CommitHistoryResult],
        node_metadata,
        file_contents,
        llm_provider,
        all_tier_files: Set[str],
    ) -> List[FileOrderEntry]:
        if not tier_files:
            return []
        if len(tier_files) == 1:
            return [FileOrderEntry(path=tier_files[0], tie_break_method="none")]

        if (
            commit_history
            and commit_history.history_available
            and commit_history.history_confidence != "reduced"
            and commit_history.file_first_appearance
        ):
            history_entries: List[Tuple[str, str]] = []
            has_full_history = True
            for f in tier_files:
                fa = commit_history.file_first_appearance.get(f)
                if fa and fa.timestamp:
                    history_entries.append((f, fa.timestamp))
                else:
                    has_full_history = False
                    break

            # PRE-FIX BUG B GUARD: All timestamps in tier had to be strictly unique
            if has_full_history:
                timestamps = [ts for _, ts in history_entries]
                if len(set(timestamps)) == len(timestamps):
                    history_entries.sort(key=lambda x: x[1])
                    return [
                        FileOrderEntry(path=f, tie_break_method="history")
                        for f, _ in history_entries
                    ]

        # Dropped entire tier to domain heuristic
        return self._refine_subgroup_heuristics_or_llm(
            subgroup_files=tier_files,
            node_metadata=node_metadata,
            file_contents=file_contents,
            llm_provider=llm_provider,
            all_tier_files=all_tier_files,
            tier_files=tier_files,
        )


def main():
    repo_dir = Path("tests/fixtures/real_repos/flask")
    assert repo_dir.exists(), f"Fixture directory not found: {repo_dir}"

    print("=" * 80)
    print("REPRODUCIBLE BUG A & BUG B EMPIRICAL COMPARISON")
    print("Fixture: tests/fixtures/real_repos/flask (5,557 commits)")
    print("=" * 80)

    # 1. Collect files & parse
    all_repo_paths = []
    py_contents = {}
    for p in repo_dir.rglob("*"):
        if ".git" in p.parts:
            continue
        if p.is_file():
            rel = p.relative_to(repo_dir).as_posix()
            all_repo_paths.append(rel)
            if rel.endswith(".py"):
                try:
                    py_contents[rel] = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass

    parser = PythonLanguageParser()
    parse_result = parser.parse_repository(list(py_contents.keys()), py_contents)

    seg_engine = SegmentationEngine()
    seg_result = seg_engine.segment_repository(parse_result.files, all_repo_paths)

    ordering_engine = BaselineOrderingEngine()
    baseline_result = ordering_engine.compute_baseline_order(
        file_nodes=parse_result.files,
        segmentation_result=seg_result,
        all_repo_files=all_repo_paths,
        file_contents=py_contents,
    )

    # 2. Extract real history (Post-Bug-A: with targeted --follow recovery)
    extractor = HistoryExtractorService()
    post_bug_a_history = extractor.extract_history(repo_dir)

    # 3. Construct Pre-Bug-A history (without --follow recovery: restructure files revert to 2019-06-01)
    pre_bug_a_map = {}
    for p, fa in post_bug_a_history.file_first_appearance.items():
        if fa.was_rename:
            # Revert to restructure commit date
            pre_bug_a_map[p] = FirstAppearance(
                commit_hash="ca278a86",
                timestamp="2019-06-01T00:00:00+00:00",
                was_rename=False,
                original_path=None,
            )
        else:
            pre_bug_a_map[p] = fa

    pre_bug_a_history = CommitHistoryResult(
        history_available=post_bug_a_history.history_available,
        commits=post_bug_a_history.commits,
        file_first_appearance=pre_bug_a_map,
        history_confidence=post_bug_a_history.history_confidence,
        commit_count_processed=post_bug_a_history.commit_count_processed,
        commit_count_total=post_bug_a_history.commit_count_total,
    )

    scorer = ConfidenceScoringEngine()

    # --- EXECUTE PRE-FIX RUN (Bug A active + Bug B active) ---
    pre_tie_breaker = PreFixTieBreakerEngine()
    pre_refined = pre_tie_breaker.refine_baseline_order(
        baseline_result, pre_bug_a_history, py_contents
    )
    pre_scored = scorer.compute_confidence_scores(pre_refined, pre_bug_a_history)

    pre_code_confs = Counter(f.confidence for f in pre_scored.files if f.path.endswith(".py"))
    pre_code_methods = Counter(f.tie_break_method for f in pre_scored.files if f.path.endswith(".py"))
    pre_tier_methods = Counter(e.tie_break_method for t in pre_refined.tiers for e in t.ordered_files)

    # --- EXECUTE POST-FIX RUN (Bug A fixed + Bug B fixed) ---
    post_tie_breaker = ConstrainedTieBreakerEngine()
    post_refined = post_tie_breaker.refine_baseline_order(
        baseline_result, post_bug_a_history, py_contents
    )
    post_scored = scorer.compute_confidence_scores(post_refined, post_bug_a_history)

    post_code_confs = Counter(f.confidence for f in post_scored.files if f.path.endswith(".py"))
    post_code_methods = Counter(f.tie_break_method for f in post_scored.files if f.path.endswith(".py"))
    post_tier_methods = Counter(e.tie_break_method for t in post_refined.tiers for e in t.ordered_files)

    print("\n" + "=" * 80)
    print("1. PRE-FIX RESULTS (Bug A + Bug B Active):")
    print("=" * 80)
    print(f"code_files_confidence_breakdown = {dict(pre_code_confs)}")
    print(f"code_files_methods_breakdown    = {dict(pre_code_methods)}  (Sum: {sum(pre_code_methods.values())})")
    print(f"tier_methods_breakdown          = {dict(pre_tier_methods)}  (Sum: {sum(pre_tier_methods.values())})")

    print("\n" + "=" * 80)
    print("2. POST-FIX RESULTS (Bug A + Bug B Fixed):")
    print("=" * 80)
    print(f"code_files_confidence_breakdown = {dict(post_code_confs)}")
    print(f"code_files_methods_breakdown    = {dict(post_code_methods)}  (Sum: {sum(post_code_methods.values())})")
    print(f"tier_methods_breakdown          = {dict(post_tier_methods)}  (Sum: {sum(post_tier_methods.values())})")
    print("=" * 80)


if __name__ == "__main__":
    main()
