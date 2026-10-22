"""Tests for Confidence Consistency between Report KPI and Scored Files Table."""

import re
from app.sequence.schema import (
    RepoConfidenceSummary,
    ScoredFileEntry,
    ScoredOrderingResult,
)
from app.sequence.narration_engine import NarrationEngine
from app.ui.components import report_view


def test_chart_and_table_percentages_are_equal():
    """Verify report KPI (chart/overview card) and scored-files table have identical percentages."""
    # 1. Prepare ScoredOrderingResult with known confidence distribution
    # 20% high, 26% medium, 54% low
    summary = RepoConfidenceSummary(
        high_pct=20.0,
        medium_pct=26.0,
        low_pct=54.0,
        history_available=False,
    )
    scored_result = ScoredOrderingResult(
        files=[
            ScoredFileEntry(path="a.py", confidence="high", confidence_reason="verified imports", tier_index=0),
            ScoredFileEntry(path="b.py", confidence="medium", confidence_reason="pattern inference", tier_index=0),
            ScoredFileEntry(path="c.py", confidence="low", confidence_reason="isolated", tier_index=0),
        ],
        repo_confidence_summary=summary,
        isolated_files=[],
        cyclic_files=[],
    )

    # 2. Build the markdown table via NarrationEngine
    engine = NarrationEngine()
    table_md = engine._build_confidence_disclosure(scored_result)

    # Verify table contains (54%) in the Low column
    total_row = [line for line in table_md.splitlines() if "**Total Scored Files**" in line]
    assert len(total_row) == 1, f"Could not find Total Scored Files row in table: {table_md}"
    cells = [c.strip() for c in total_row[0].split("|") if c.strip()]
    # cells: ['**Total Scored Files**', '**1** (20%)', '**1** (26%)', '**1** (54%)', '**3** (100%)', '-']
    assert len(cells) >= 4, f"Unexpected cells in row: {cells}"
    table_low_match = re.search(r"\((\d+(?:\.\d+)?)%\)", cells[3])
    assert table_low_match is not None, f"Could not parse low percentage from cell {cells[3]}"
    table_low_pct = float(table_low_match.group(1))
    assert table_low_pct == 54.0

    # 3. Render report view with persisted confidence_summary in graph_data
    graph_data = {
        "nodes": [{"id": "a.py", "confidence": "high"}, {"id": "b.py", "confidence": "medium"}, {"id": "c.py", "confidence": "low"}],
        "edges": [],
        "confidence_summary": summary.model_dump(),
    }
    job = {
        "id": 101,
        "repo_url": "https://github.com/org/repo",
        "repo_name": "repo",
    }
    report_html = report_view(job=job, raw_markdown=table_md, graph_data=graph_data, quiz_data=None)

    # 4. Extract KPI confidence from overview card
    # Should say: "Share of files with low confidence: 54%"
    assert "LOW (54%)" not in report_html
    assert "Share of files with low confidence: 54%" in report_html

    kpi_low_match = re.search(r"Share of files with low confidence:\s*(\d+(?:\.\d+)?)%", report_html)
    assert kpi_low_match is not None, f"Could not find low confidence KPI in html: {report_html}"
    kpi_low_pct = float(kpi_low_match.group(1))

    # Assert chart and table percentages are equal
    assert kpi_low_pct == table_low_pct == 54.0


def test_high_confidence_chart_and_table_equal():
    """Verify high confidence numbers match between table and KPI."""
    summary = RepoConfidenceSummary(
        high_pct=80.0,
        medium_pct=15.0,
        low_pct=5.0,
        history_available=True,
    )
    scored_result = ScoredOrderingResult(
        files=[ScoredFileEntry(path="a.py", confidence="high", confidence_reason="verified imports", tier_index=0)],
        repo_confidence_summary=summary,
        isolated_files=[],
        cyclic_files=[],
    )
    engine = NarrationEngine()
    table_md = engine._build_confidence_disclosure(scored_result)

    # Extract high percentage from table
    total_row = [line for line in table_md.splitlines() if "**Total Scored Files**" in line]
    assert len(total_row) == 1
    cells = [c.strip() for c in total_row[0].split("|") if c.strip()]
    table_high_match = re.search(r"\((\d+(?:\.\d+)?)%\)", cells[1])
    assert table_high_match is not None
    table_high_pct = float(table_high_match.group(1))
    assert table_high_pct == 80.0

    graph_data = {
        "nodes": [{"id": "a.py", "confidence": "high"}],
        "edges": [],
        "confidence_summary": summary.model_dump(),
    }
    job = {"id": 102, "repo_name": "repo"}
    report_html = report_view(job=job, raw_markdown=table_md, graph_data=graph_data, quiz_data=None)

    assert "HIGH (80%)" in report_html
    kpi_high_match = re.search(r"HIGH \((\d+(?:\.\d+)?)%\)", report_html)
    assert kpi_high_match is not None
    kpi_high_pct = float(kpi_high_match.group(1))
    assert kpi_high_pct == table_high_pct == 80.0


def test_old_job_fallback_estimated_from_graph_nodes():
    """Verify old jobs without confidence_summary fall back to nodes with 'estimated from graph nodes'."""
    graph_data = {
        "nodes": [
            {"id": "a.py", "confidence": "low"},
            {"id": "b.py", "confidence": "low"},
        ],
        "edges": [],
        # No confidence_summary key
    }
    job = {"id": 103, "repo_name": "old-job"}
    report_html = report_view(job=job, raw_markdown="", graph_data=graph_data, quiz_data=None)

    assert "estimated from graph nodes" in report_html
    assert "LOW (100%)" not in report_html
    assert "Share of files with low confidence: 100%" in report_html
