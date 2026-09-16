"""Real empirical check on pallets/flask with Bug A and Bug B active.

Executes the full pipeline:
Ingestion -> Parsing -> Segmentation -> Baseline Ordering -> History Extraction -> Constrained Tie-Breaking -> Confidence Scoring
Outputs actual raw dictionary counts for tie-breaking methods and confidence levels.
"""

import sys
import time
from collections import Counter
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parser.python_parser import PythonLanguageParser
from app.segmentation.engine import SegmentationEngine
from app.sequence.baseline_ordering import BaselineOrderingEngine
from app.sequence.constrained_tie_breaking import ConstrainedTieBreakerEngine
from app.sequence.confidence_scoring import ConfidenceScoringEngine
from app.services.history_extractor import HistoryExtractorService


def run_flask_empirical():
    repo_dir = Path("tests/fixtures/real_repos/flask")
    assert repo_dir.exists(), f"Fixture directory not found: {repo_dir}"

    print("=" * 80)
    print("EXECUTING REAL FLASK EMPIRICAL PIPELINE CHECK (BUG A + BUG B ACTIVE)")
    print("=" * 80)

    # 1. Collect all repo paths and python source contents at HEAD
    all_repo_paths = []
    py_contents = {}
    for p in repo_dir.rglob("*"):
        if ".git" in p.parts:
            continue
        if p.is_file():
            rel_path = p.relative_to(repo_dir).as_posix()
            all_repo_paths.append(rel_path)
            if rel_path.endswith(".py"):
                try:
                    py_contents[rel_path] = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass

    print(f"Total repository files at HEAD: {len(all_repo_paths)}")
    print(f"Total Python source files:      {len(py_contents)}")

    # 2. Layer 2: Parsing
    t0 = time.time()
    parser = PythonLanguageParser()
    parse_result = parser.parse_repository(list(py_contents.keys()), py_contents)
    t_parse = time.time() - t0
    print(f"Parsing completed in {t_parse:.2f}s ({len(parse_result.files)} files parsed)")

    # 3. Layer 4: Segmentation
    t0 = time.time()
    seg_engine = SegmentationEngine()
    seg_result = seg_engine.segment_repository(parse_result.files, all_repo_paths)
    t_seg = time.time() - t0
    print(f"Segmentation completed in {t_seg:.2f}s")

    # 4. Layer 6 Stage A: Baseline Ordering
    t0 = time.time()
    ordering_engine = BaselineOrderingEngine()
    baseline_result = ordering_engine.compute_baseline_order(
        file_nodes=parse_result.files,
        segmentation_result=seg_result,
        all_repo_files=all_repo_paths,
        file_contents=py_contents,
    )
    t_stage_a = time.time() - t0
    print(f"Stage A Baseline Ordering completed in {t_stage_a:.2f}s")
    print(f"  Tiers: {len(baseline_result.tiers)}, Tier files: {sum(len(t.files) for t in baseline_result.tiers)}")
    print(f"  Isolated files: {len(baseline_result.isolated_files)}")
    print(f"  Cyclic files:   {len(baseline_result.cyclic_files)}")

    # 5. Layer 3: History Extraction (with Bug A --follow recovery)
    t0 = time.time()
    extractor = HistoryExtractorService()
    history_result = extractor.extract_history(repo_dir)
    t_hist = time.time() - t0
    print(f"History Extraction completed in {t_hist:.2f}s")
    print(f"  Total commits:    {history_result.commit_count_total}")
    print(f"  Processed:        {history_result.commit_count_processed}")
    print(f"  Confidence:       '{history_result.history_confidence}'")
    print(f"  First appearances:{len(history_result.file_first_appearance)}")

    # 6. Layer 6 Stage B: Constrained Tie-Breaking (with Bug B partial ordering)
    t0 = time.time()
    tie_breaker = ConstrainedTieBreakerEngine()
    refined_result = tie_breaker.refine_baseline_order(
        baseline_result=baseline_result,
        commit_history=history_result,
        file_contents=py_contents,
    )
    t_stage_b = time.time() - t0
    print(f"Stage B Tie-Breaking completed in {t_stage_b:.2f}s")

    # 7. Layer 6 Stage C: Confidence Scoring
    t0 = time.time()
    scorer = ConfidenceScoringEngine()
    scored_result = scorer.compute_confidence_scores(
        refined_result=refined_result,
        commit_history=history_result,
    )
    t_stage_c = time.time() - t0
    print(f"Stage C Confidence Scoring completed in {t_stage_c:.2f}s")

    # 8. Compute RAW Empirical Counts
    tier_methods = Counter(
        entry.tie_break_method
        for tier in refined_result.tiers
        for entry in tier.ordered_files
    )
    all_methods = Counter(entry.tie_break_method for entry in scored_result.files)
    all_confs = Counter(f.confidence for f in scored_result.files)

    code_confs = Counter(
        f.confidence for f in scored_result.files if f.path.endswith(".py")
    )
    code_methods = Counter(
        f.tie_break_method for f in scored_result.files if f.path.endswith(".py")
    )

    print("\n" + "=" * 80)
    print("RAW EMPIRICAL METRICS (FLASK):")
    print("=" * 80)
    print(f"tier_methods_breakdown = {dict(tier_methods)}")
    print(f"all_files_methods_breakdown = {dict(all_methods)}")
    print(f"all_files_confidence_breakdown = {dict(all_confs)}")
    print(f"code_files_confidence_breakdown = {dict(code_confs)}")
    print(f"code_files_methods_breakdown = {dict(code_methods)}")
    print(f"repo_confidence_summary = {scored_result.repo_confidence_summary}")
    print("=" * 80)


if __name__ == "__main__":
    run_flask_empirical()
