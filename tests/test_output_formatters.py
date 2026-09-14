"""Unit tests for Layer 8 Output Formatters."""

import pytest
from app.formatters.graph_formatter import GraphExportFormatter
from app.formatters.markdown_formatter import MarkdownReportFormatter
from app.formatters.quiz_formatter import QuizFormatter
from app.synthesis.schema import ArchitectureOverview, SynthesizedMilestone, SynthesizedRepositoryReport


@pytest.fixture
def sample_report():
    ov = ArchitectureOverview(
        total_files=3,
        total_domains=3,
        domain_file_counts={"core": 1, "backend": 1, "tests": 1},
        primary_language="python",
        entry_point_files=["src/main.py"],
        cyclic_cluster_file_count=0,
        isolated_file_count=0,
    )
    m0 = SynthesizedMilestone(
        tier=0,
        title="Foundational Utilities",
        summary="Zero-dependency primitives.",
        dominant_domain="backend",
        domain_breakdown={"backend": 1},
        files=["src/utils.py"],
        confidence="high",
        architectural_role="Foundational Primitives",
        key_symbols_and_exports=["helper"],
        deep_dive_citations=["src/utils.py"],
        pedagogical_hints=["Start here."],
        implementation_gotchas=["Watch out for None return values."],
    )
    m1 = SynthesizedMilestone(
        tier=1,
        title="Application Core",
        summary="Main application entry point.",
        dominant_domain="core",
        domain_breakdown={"core": 1},
        files=["src/main.py"],
        confidence="high",
        architectural_role="Core Domain Extensions",
        key_symbols_and_exports=["main"],
    )
    return SynthesizedRepositoryReport(
        repo_name="demo-repo",
        architecture_overview=ov,
        confidence_disclosure="66.7% backed by deterministic topology.",
        milestones=[m0, m1],
        total_milestones=2,
        synthesis_timestamp="2026-09-14T12:00:00Z",
    )


def test_markdown_formatter_renders_full_document(sample_report):
    formatter = MarkdownReportFormatter()
    md = formatter.format_report(sample_report)

    assert "# Architectural Reverse-Engineering Report: `demo-repo`" in md
    assert "## 1. Executive Architecture Overview" in md
    assert "## 2. Sequence Reasoning & Confidence Calibration" in md
    assert "## 3. Step-by-Step Architectural Milestones" in md
    assert "### Milestone 0: Foundational Utilities" in md
    assert "**[HIGH CONFIDENCE]**" in md
    assert "Watch out for None return values." in md


def test_graph_formatter_json_and_mermaid(sample_report):
    formatter = GraphExportFormatter()
    
    # JSON DAG
    json_dag = formatter.format_json_dag(sample_report)
    assert json_dag["repo_name"] == "demo-repo"
    assert json_dag["total_nodes"] == 2
    assert any(n["id"] == "src/utils.py" for n in json_dag["nodes"])

    # Mermaid
    mermaid = formatter.format_mermaid(sample_report)
    assert "graph TD" in mermaid
    assert "subgraph Tier_0" in mermaid
    assert "subgraph Tier_1" in mermaid
    assert "Tier_0 --> Tier_1" in mermaid


def test_quiz_formatter_generates_educational_questions(sample_report):
    formatter = QuizFormatter()
    quiz = formatter.generate_quiz(sample_report)

    assert quiz["repo_name"] == "demo-repo"
    assert quiz["total_questions"] >= 2
    assert any("Foundational Utilities" in q["question"] for q in quiz["questions"])
