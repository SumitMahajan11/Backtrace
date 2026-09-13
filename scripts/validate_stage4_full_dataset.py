"""Stage 4 (Layer 6 Stages A, B, C) Full Dataset Sequence Reasoning Validation Script.

Fetches the complete, exact recursive file trees and file contents for pallets/flask and gin-gonic/gin via GitHub API,
runs Layer 2 parsing + Layer 4 segmentation + Layer 6 Stage A, B, C pipeline across ALL real repo files,
and reports full tier distribution, isolated file rates, and confidence metrics at scale.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parser.python_parser import PythonLanguageParser
from app.parser.go_parser import GoLanguageParser
from app.segmentation.engine import SegmentationEngine
from app.sequence.baseline_ordering import BaselineOrderingEngine
from app.sequence.constrained_tie_breaking import ConstrainedTieBreakerEngine
from app.sequence.confidence_scoring import ConfidenceScoringEngine


def fetch_repo_tree_and_contents(repo: str, branch: str, file_extensions: Set[str]) -> Tuple[List[str], Dict[str, str]]:
    """Fetches full file tree and code contents for matching source files from GitHub API."""
    url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
    headers = {"User-Agent": "Python-Stage4-Validator"}
    req = urllib.request.Request(url, headers=headers)
    
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        all_tree_items = data.get("tree", [])

    all_file_paths = [item["path"] for item in all_tree_items if item.get("type") == "blob"]
    code_contents: Dict[str, str] = {}

    target_items = [
        item for item in all_tree_items
        if item.get("type") == "blob" and any(item["path"].endswith(ext) for ext in file_extensions)
    ]

    print(f"  Fetching content for {len(target_items)} source files in {repo}...", flush=True)

    for item in target_items:
        path = item["path"]
        raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
        try:
            raw_req = urllib.request.Request(raw_url, headers=headers)
            with urllib.request.urlopen(raw_req) as raw_resp:
                code_contents[path] = raw_resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"    Warning: Could not fetch {path}: {e}", flush=True)

    return all_file_paths, code_contents


def validate_flask_full():
    print("\n" + "=" * 100, flush=True)
    print("RUNNING LAYER 6 (STAGES A, B, C) FULL-SCALE VALIDATION ON PALLETS/FLASK", flush=True)
    print("=" * 100, flush=True)

    repo = "pallets/flask"
    branch = "main"
    all_paths, code_contents = fetch_repo_tree_and_contents(repo, branch, {".py"})

    print(f"  Total Repository Blobs: {len(all_paths)}", flush=True)
    print(f"  Total Python Files Fetched: {len(code_contents)}", flush=True)

    # 1. Layer 2 Parsing across all python files
    py_parser = PythonLanguageParser()
    parse_result = py_parser.parse_repository(
        file_paths=list(code_contents.keys()),
        file_contents=code_contents,
    )
    print(f"  Parsed FileNodes: {len(parse_result.files)}", flush=True)

    # 2. Layer 4 Segmentation across full repo
    seg_engine = SegmentationEngine()
    seg_result = seg_engine.segment_repository(parse_result.files, all_paths)

    # 3. Layer 6 Stage A: Baseline Ordering (with intra-package symbol linking)
    stage_a = BaselineOrderingEngine()
    a_result = stage_a.compute_baseline_order(
        file_nodes=parse_result.files,
        segmentation_result=seg_result,
        all_repo_files=all_paths,
        file_contents=code_contents,
    )

    # 4. Layer 6 Stage B: Constrained Tie-Breaking
    stage_b = ConstrainedTieBreakerEngine()
    b_result = stage_b.refine_baseline_order(a_result, file_contents=code_contents)

    # 5. Layer 6 Stage C: Confidence Scoring
    stage_c = ConfidenceScoringEngine()
    c_result = stage_c.compute_confidence_scores(b_result)

    py_isolated = [f for f in b_result.isolated_files if f.endswith(".py")]
    py_cyclic = [f for f in b_result.cyclic_files if f.endswith(".py")]

    print("\n  FULL FLASK SEQUENCE REASONING METRICS:", flush=True)
    print(f"    --- Denominator 1: Total Repository Blobs ({len(c_result.files)} blobs) ---", flush=True)
    print(f"      Total Isolated Blobs: {len(b_result.isolated_files)} ({(len(b_result.isolated_files)/len(c_result.files))*100:.2f}%)", flush=True)
    print(f"      Total Cyclic Blobs: {len(b_result.cyclic_files)} ({(len(b_result.cyclic_files)/len(c_result.files))*100:.2f}%)", flush=True)
    print(f"      Confidence Summary (Total Blobs): High={c_result.repo_confidence_summary.high_pct}%, Medium={c_result.repo_confidence_summary.medium_pct}%, Low={c_result.repo_confidence_summary.low_pct}%", flush=True)

    print(f"\n    --- Denominator 2: Code Files Only ({len(code_contents)} Python files) ---", flush=True)
    print(f"      Isolated Python Files: {len(py_isolated)} / {len(code_contents)} ({(len(py_isolated)/len(code_contents))*100:.2f}%)", flush=True)
    print(f"      Cyclic Python Files: {len(py_cyclic)} / {len(code_contents)} ({(len(py_cyclic)/len(code_contents))*100:.2f}%)", flush=True)
    
    # Calculate code-only confidence summary
    code_entries = [e for e in c_result.files if e.path.endswith(".py")]
    code_high = sum(1 for e in code_entries if e.confidence == "high")
    code_med = sum(1 for e in code_entries if e.confidence == "medium")
    code_low = sum(1 for e in code_entries if e.confidence == "low")
    c_total = len(code_entries) or 1
    print(f"      Confidence Summary (Code Files): High={(code_high/c_total)*100:.2f}%, Medium={(code_med/c_total)*100:.2f}%, Low={(code_low/c_total)*100:.2f}%", flush=True)

    print("\n  TIER BREAKDOWN AT SCALE (FLASK):", flush=True)
    for tier in b_result.tiers:
        print(f"    Tier {tier.tier_index:2d} ({len(tier.ordered_files):2d} files): {[f.path for f in tier.ordered_files[:5]]}{'...' if len(tier.ordered_files) > 5 else ''}", flush=True)

    return c_result


def validate_gin_full():
    print("\n" + "=" * 100, flush=True)
    print("RUNNING LAYER 6 (STAGES A, B, C) FULL-SCALE VALIDATION ON GIN-GONIC/GIN", flush=True)
    print("=" * 100, flush=True)

    repo = "gin-gonic/gin"
    branch = "master"
    all_paths, code_contents = fetch_repo_tree_and_contents(repo, branch, {".go"})

    print(f"  Total Repository Blobs: {len(all_paths)}", flush=True)
    print(f"  Total Go Files Fetched: {len(code_contents)}", flush=True)

    # 1. Layer 2 Parsing across all go files
    go_parser = GoLanguageParser()
    parse_result = go_parser.parse_repository(
        file_paths=list(code_contents.keys()),
        file_contents=code_contents,
    )
    print(f"  Parsed FileNodes: {len(parse_result.files)}", flush=True)

    # 2. Layer 4 Segmentation across full repo
    seg_engine = SegmentationEngine()
    seg_result = seg_engine.segment_repository(parse_result.files, all_paths)

    # 3. Layer 6 Stage A: Baseline Ordering (with intra-package symbol linking)
    stage_a = BaselineOrderingEngine()
    a_result = stage_a.compute_baseline_order(
        file_nodes=parse_result.files,
        segmentation_result=seg_result,
        all_repo_files=all_paths,
        file_contents=code_contents,
    )

    # 4. Layer 6 Stage B: Constrained Tie-Breaking
    stage_b = ConstrainedTieBreakerEngine()
    b_result = stage_b.refine_baseline_order(a_result, file_contents=code_contents)

    # 5. Layer 6 Stage C: Confidence Scoring
    stage_c = ConfidenceScoringEngine()
    c_result = stage_c.compute_confidence_scores(b_result)

    go_isolated = [f for f in b_result.isolated_files if f.endswith(".go")]
    go_cyclic = [f for f in b_result.cyclic_files if f.endswith(".go")]

    print("\n  FULL GIN SEQUENCE REASONING METRICS:", flush=True)
    print(f"    --- Denominator 1: Total Repository Blobs ({len(c_result.files)} blobs) ---", flush=True)
    print(f"      Total Isolated Blobs: {len(b_result.isolated_files)} ({(len(b_result.isolated_files)/len(c_result.files))*100:.2f}%)", flush=True)
    print(f"      Total Cyclic Blobs: {len(b_result.cyclic_files)} ({(len(b_result.cyclic_files)/len(c_result.files))*100:.2f}%)", flush=True)
    print(f"      Confidence Summary (Total Blobs): High={c_result.repo_confidence_summary.high_pct}%, Medium={c_result.repo_confidence_summary.medium_pct}%, Low={c_result.repo_confidence_summary.low_pct}%", flush=True)

    print(f"\n    --- Denominator 2: Code Files Only ({len(code_contents)} Go files) ---", flush=True)
    print(f"      Isolated Go Files: {len(go_isolated)} / {len(code_contents)} ({(len(go_isolated)/len(code_contents))*100:.2f}%)", flush=True)
    print(f"      Cyclic Go Files: {len(go_cyclic)} / {len(code_contents)} ({(len(go_cyclic)/len(code_contents))*100:.2f}%)", flush=True)

    code_entries = [e for e in c_result.files if e.path.endswith(".go")]
    code_high = sum(1 for e in code_entries if e.confidence == "high")
    code_med = sum(1 for e in code_entries if e.confidence == "medium")
    code_low = sum(1 for e in code_entries if e.confidence == "low")
    c_total = len(code_entries) or 1
    print(f"      Confidence Summary (Code Files): High={(code_high/c_total)*100:.2f}%, Medium={(code_med/c_total)*100:.2f}%, Low={(code_low/c_total)*100:.2f}%", flush=True)

    print("\n  TIER BREAKDOWN AT SCALE (GIN):", flush=True)
    for tier in b_result.tiers:
        print(f"    Tier {tier.tier_index:2d} ({len(tier.ordered_files):2d} files): {[f.path for f in tier.ordered_files[:5]]}{'...' if len(tier.ordered_files) > 5 else ''}", flush=True)

    return c_result


if __name__ == "__main__":
    validate_flask_full()
    validate_gin_full()
