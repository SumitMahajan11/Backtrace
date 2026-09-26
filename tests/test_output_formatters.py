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
        file_symbols={
            "src/utils.py": ["helper"],
            "src/main.py": ["main"],
        },
        file_dependencies=[
            {"source": "src/main.py", "target": "src/utils.py", "type": "import"}
        ],
    )


def test_markdown_formatter_renders_full_document(sample_report):
    formatter = MarkdownReportFormatter()
    md = formatter.format_report(sample_report)

    assert "# Architectural Reverse-Engineering Report: `demo-repo`" in md
    assert "## 1. Executive Architecture Overview" in md
    assert "## 2. Build Order & Confidence Scoring" in md
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
    assert len(json_dag["edges"]) == 1
    assert json_dag["edges"][0]["source"] == "src/main.py"
    assert json_dag["edges"][0]["target"] == "src/utils.py"

    utils_node = next(n for n in json_dag["nodes"] if n["id"] == "src/utils.py")
    assert utils_node["exports"] == ["helper"]

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
    for q in quiz["questions"]:
        assert "tier" in q
        assert isinstance(q["tier"], int)


def test_quiz_multiple_tiers_badge_rendering():
    """Validates that quizzes across multiple tiers always render real tier numbers in UI badges."""
    from app.ui.components import report_view
    from app.models.db import UserModel

    ov = ArchitectureOverview(
        total_files=6,
        total_domains=3,
        domain_file_counts={"database": 2, "core": 2, "api": 2},
        primary_language="python",
        entry_point_files=["src/server.py"],
        cyclic_cluster_file_count=2,
        isolated_file_count=0,
    )
    m0 = SynthesizedMilestone(
        tier=0,
        title="Database Models",
        summary="Foundational models.",
        dominant_domain="database",
        files=["src/models.py"],
        confidence="high",
    )
    m1 = SynthesizedMilestone(
        tier=1,
        title="Core Subsystem (Cyclic)",
        summary="Cyclic core subsystem.",
        dominant_domain="core",
        files=["src/core_a.py", "src/core_b.py"],
        confidence="low",
        is_cyclic=True,
    )
    m2 = SynthesizedMilestone(
        tier=2,
        title="Service Layer",
        summary="Business service logic.",
        dominant_domain="core",
        files=["src/service.py"],
        confidence="medium",
    )
    m3 = SynthesizedMilestone(
        tier=3,
        title="API Server",
        summary="Top level API server.",
        dominant_domain="api",
        files=["src/server.py"],
        confidence="high",
    )
    report = SynthesizedRepositoryReport(
        repo_name="multitier-repo",
        architecture_overview=ov,
        confidence_disclosure="Multi-tier verification.",
        milestones=[m0, m1, m2, m3],
        total_milestones=4,
        synthesis_timestamp="2026-09-24T12:00:00Z",
    )

    formatter = QuizFormatter()
    quiz = formatter.generate_quiz(report)

    assert quiz["total_questions"] >= 4
    # Verify every question has a valid integer tier
    for q in quiz["questions"]:
        assert "tier" in q
        assert isinstance(q["tier"], int)
        assert q["tier"] in [0, 1, 2, 3]

    # Render via UI report_view and verify badges
    dummy_user = UserModel(id=1, github_id=12345, github_username="tester", email="tester@example.com")
    job_mock = {
        "id": 42,
        "repo_name": "multitier-repo",
        "repo_url": "https://github.com/example/multitier-repo",
        "created_at": "2026-09-24 12:00:00 UTC",
        "execution_time_seconds": 2.5,
        "run_id": "run_42",
    }
    raw_md = "# Architectural Reverse-Engineering Report: `multitier-repo`\n## 1. Executive Architecture Overview\n## 2. Build Order & Confidence Scoring\n## 3. Step-by-Step Architectural Milestones\n"
    html = report_view(
        job=job_mock,
        raw_markdown=raw_md,
        graph_data={"nodes": [], "edges": []},
        quiz_data=quiz,
        current_user=dummy_user,
    )

    # Ensure no placeholder em-dash or None appears in any tier invariant tag
    assert "Tier — Invariant" not in html
    assert "Tier None Invariant" not in html
    assert "Tier 0 Invariant" in html
    assert "Tier 1 Invariant" in html
    assert "Tier 2 Invariant" in html
    assert "Tier 3 Invariant" in html


def test_unified_domain_colors_and_multi_domain_legend():
    """Validates that Overview breakdown bars and DAG legend share identical colors and reflect all present domains."""
    from app.ui.components import report_view
    from app.formatters.graph_formatter import DOMAIN_HEX_COLORS
    from app.models.db import UserModel

    dummy_user = UserModel(id=2, github_id=9999, github_username="tester2", email="tester2@example.com")
    job_mock = {
        "id": 99,
        "repo_name": "full-stack-repo",
        "repo_url": "https://github.com/example/full-stack-repo",
        "created_at": "2026-09-24 12:00:00 UTC",
        "execution_time_seconds": 3.0,
        "run_id": "run_99",
    }
    raw_md = """# Architectural Reverse-Engineering Report: `full-stack-repo`
## 1. Executive Architecture Overview
- **Repository**: `full-stack-repo`
- **Total Analyzed Files**: `6`
- **Primary Language**: `Python`
- **Subsystem Domains**:
  - `core`: 1 files (16.7%)
  - `backend`: 1 files (16.7%)
  - `frontend`: 1 files (16.7%)
  - `database`: 1 files (16.7%)
  - `config`: 1 files (16.7%)
  - `tests`: 1 files (16.7%)

## 2. Build Order & Confidence Scoring
Calibration note.

## 3. Step-by-Step Architectural Milestones
### Milestone 0: Core Foundation
- src/core.py
"""

    graph_nodes = [
        {"id": "src/core.py", "path": "src/core.py", "domain": "core", "tier": 0, "confidence": "high"},
        {"id": "src/backend.py", "path": "src/backend.py", "domain": "backend", "tier": 1, "confidence": "high"},
        {"id": "src/ui.py", "path": "src/ui.py", "domain": "frontend", "tier": 2, "confidence": "medium"},
        {"id": "src/db.py", "path": "src/db.py", "domain": "database", "tier": 0, "confidence": "high"},
        {"id": "config.yaml", "path": "config.yaml", "domain": "config", "tier": 0, "confidence": "medium"},
        {"id": "tests/test.py", "path": "tests/test.py", "domain": "tests", "tier": 3, "confidence": "low"},
    ]

    html = report_view(
        job=job_mock,
        raw_markdown=raw_md,
        graph_data={"nodes": graph_nodes, "edges": []},
        quiz_data=None,
        current_user=dummy_user,
    )

    # 1. Verify Subsystem Breakdown bars use DOMAIN_HEX_COLORS
    for dom in ["core", "backend", "frontend", "database", "config", "tests"]:
        expected_color = DOMAIN_HEX_COLORS[dom]
        assert f"background: {expected_color}" in html

    # 2. Verify all 6 domains appear in the Dependency Graph Legend
    for dom in ["CORE", "BACKEND", "FRONTEND", "DATABASE", "CONFIG", "TESTS"]:
        assert f">{dom}</span>" in html


