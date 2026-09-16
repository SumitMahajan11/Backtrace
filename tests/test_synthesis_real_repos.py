"""Real-repo validation suite for Layer 7 (Synthesis Engine) & Layer 8 (Output Formatters).

Validates against the three critical failure modes:
1. Specificity: Narration references this repository's actual dependency graph rather than generic trivia.
2. Honest Calibration: Cyclic clusters and low-confidence tiers are never smoothed over into confident ordinal prose.
3. Anti-Flattening: Formatted output (Markdown and JSON) renders the full confidence breakdown alongside the badge.
"""

import json
from pathlib import Path
import pytest

from app.orchestration.pipeline import PipelineOrchestrator
from app.formatters.markdown_formatter import MarkdownReportFormatter
from app.formatters.graph_formatter import GraphExportFormatter


def test_real_flask_synthesis_and_narration():
    """
    Executes full Layer 7 Synthesis and Layer 8 Markdown/Graph formatting
    on genuine files from pallets/flask (extracted from tests/fixtures/flask_cache.json).
    """
    cache_path = Path(__file__).resolve().parent / "fixtures" / "flask_cache.json"
    assert cache_path.exists(), f"Flask cache fixture not found at {cache_path}"

    with open(cache_path, "r", encoding="utf-8") as f:
        cache_data = json.load(f)

    flask_contents = cache_data["code_contents"]
    assert len(flask_contents) == 83, f"Expected canonical 83 Flask files, found {len(flask_contents)}"

    orchestrator = PipelineOrchestrator()
    result = orchestrator.run_pipeline(
        repo_name="pallets/flask",
        file_paths=list(flask_contents.keys()),
        file_contents=flask_contents,
        enable_rag=True,
    )

    assert result.success is True
    report = result.report
    assert report is not None

    # =========================================================================
    # Test 1: Specificity — Prose ties directly to repo graph, not generic trivia
    # =========================================================================
    ov = report.architecture_overview
    assert ov.primary_language == "python"
    assert ov.total_files == 83
    assert "core" in ov.domain_file_counts
    assert "tests" in ov.domain_file_counts
    assert "examples" in ov.domain_file_counts
    # Entrypoints must reflect actual parsed files
    assert any("cli.py" in ep or "__main__.py" in ep for ep in ov.entry_point_files)

    # Tier 0 must identify foundation leaf primitives with zero internal dependencies
    m0 = next(m for m in report.milestones if m.tier == 0)
    assert "signals.py" in m0.files[0] or "typing.py" in m0.files[0]
    assert "zero internal dependencies" in m0.summary.lower()

    # =========================================================================
    # Test 2: Honest Calibration — Cyclic clusters are NOT smoothed over into linear prose
    # =========================================================================
    # In Flask's core, blueprints, app, ctx, config form a circular dependency cluster
    cyclic_m = next((m for m in report.milestones if m.is_cyclic), None)
    assert cyclic_m is not None, "Expected cyclic milestone in Flask core architecture"
    assert cyclic_m.confidence == "low"
    assert "src/flask/blueprints.py" in cyclic_m.files
    assert "src/flask/app.py" in cyclic_m.files

    # The narrative MUST explicitly state co-dependency and avoid ordinal ordering claims
    assert "circular dependency cluster" in cyclic_m.summary.lower() or "co-dependent" in cyclic_m.summary.lower()
    assert "studied together as a cohesive subsystem" in cyclic_m.summary.lower()
    assert "rather than in a strict linear order" in cyclic_m.summary.lower()

    # Confidence provenance must explicitly account for all files in the cluster
    assert "co-dependent files in a circular cluster" in cyclic_m.summary

    # =========================================================================
    # Test 3: Anti-Flattening & Citation Scoping Verification
    # =========================================================================
    # HARD FILTER: Every deep-dive citation in every milestone MUST belong to that milestone's files
    for m in report.milestones:
        milestone_file_set = set(m.files)
        for cite in m.deep_dive_citations:
            file_part = cite.split(":")[0]
            assert file_part in milestone_file_set, (
                f"Citation misattribution in Milestone {m.tier}: '{cite}' does not belong to {milestone_file_set}"
            )

        # Key symbols must never contain file paths
        for sym in m.key_symbols_and_exports:
            assert "/" not in sym and "\\" not in sym and not sym.endswith(".py"), (
                f"Symbol misattribution in Milestone {m.tier}: filename '{sym}' substituted as symbol"
            )

    md_output = result.markdown_output
    assert md_output is not None

    # Check that Markdown milestone header includes breakdown dictionary, not just bare badge
    # e.g., "**[LOW CONFIDENCE (Low: 19)]** *[CYCLIC CORE]*"
    assert "**[LOW CONFIDENCE (Low:" in md_output, "Markdown output failed to render confidence breakdown dict"
    assert "*[CYCLIC CORE]*" in md_output

    # Check that reconciliation table is rendered in Section 2
    assert "## 2. Sequence Reasoning & Confidence Calibration" in md_output
    assert "| Milestone / Scope | High | Medium | Low | Total Files | Dominant Domain |" in md_output

    # Graph DAG Formatter must also preserve confidence_breakdown
    graph_formatter = GraphExportFormatter()
    dag = graph_formatter.format_json_dag(report)
    assert len(dag["nodes"]) == sum(len(m.files) for m in report.milestones)
    assert len(dag["nodes"]) + ov.isolated_file_count == 83
    sample_node = next(n for n in dag["nodes"] if n["id"] == "src/flask/app.py")
    assert "confidence_breakdown" in sample_node
    assert sample_node["confidence_breakdown"] == cyclic_m.confidence_breakdown


def test_real_mixed_confidence_badge_rendering_with_history(tmp_path):
    """
    Validates Layer 8 milestone badge rendering when real Git commit history is present.
    Asserts that:
    1. A real mixed-confidence milestone renders multi-value badges (e.g. 'High: X, Medium: Y').
    2. The Markdown output explicitly displays 'Medium:' in both the reconciliation table and milestone headers.
    """
    import subprocess
    clone_dir = tmp_path / "flask_clone"
    subprocess.run(["git", "clone", "https://github.com/pallets/flask.git", str(clone_dir)], check=True, capture_output=True)

    cache_path = Path(__file__).resolve().parent / "fixtures" / "flask_cache.json"
    with open(cache_path, "r", encoding="utf-8") as f:
        cache_data = json.load(f)
    flask_contents = cache_data["code_contents"]

    orchestrator = PipelineOrchestrator()
    result = orchestrator.run_pipeline(
        repo_name="pallets/flask",
        file_paths=list(flask_contents.keys()),
        file_contents=flask_contents,
        git_repo_path=clone_dir,
        enable_rag=True,
    )

    assert result.success is True
    report = result.report
    assert report is not None

    # Verify that Medium confidence exists across milestones
    summary = report.confidence_disclosure
    assert "Medium Confidence" in summary

    # Verify at least one milestone has both High and Medium files
    mixed_m = next(
        (m for m in report.milestones if m.confidence_breakdown.get("high", 0) > 0 and m.confidence_breakdown.get("medium", 0) > 0),
        None,
    )
    assert mixed_m is not None, "Expected at least one milestone with mixed High and Medium confidence"

    md = result.markdown_output
    # Assert that the formatted badge explicitly shows both High and Medium counts in the header
    assert "Medium:" in md, "Expected 'Medium:' in Markdown output breakdown"
    assert "High:" in md, "Expected 'High:' in Markdown output breakdown"
    assert "**[HIGH CONFIDENCE (High:" in md, "Expected breakdown badge in Markdown output"

