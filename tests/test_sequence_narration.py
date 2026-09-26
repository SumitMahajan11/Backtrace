"""Unit tests for Layer 6 (Stage D) Sequence Narration Engine & Prompt Design."""

import pytest
from app.sequence.narration_engine import NarrationEngine, STAGE_D_SYSTEM_PROMPT
from app.sequence.schema import (
    RepoConfidenceSummary,
    ScoredFileEntry,
    ScoredOrderingResult,
)


@pytest.fixture
def sample_scored_result() -> ScoredOrderingResult:
    """Constructs a representative ScoredOrderingResult with mixed tiers, cycles, and isolated files."""
    files = [
        # Tier 0 (Foundation - High Confidence)
        ScoredFileEntry(
            path="src/config.py",
            tier_index=0,
            confidence="high",
            confidence_reason="topology + verified history",
            tie_break_method="history",
        ),
        ScoredFileEntry(
            path="src/constants.py",
            tier_index=0,
            confidence="high",
            confidence_reason="topology + verified history",
            tie_break_method="history",
        ),
        # Tier 1 (Core Cyclic Cluster - Low Confidence)
        ScoredFileEntry(
            path="src/app.py",
            tier_index=1,
            confidence="low",
            confidence_reason="cyclic cluster (circular dependency)",
            tie_break_method="history",
        ),
        ScoredFileEntry(
            path="src/routes.py",
            tier_index=1,
            confidence="low",
            confidence_reason="cyclic cluster (circular dependency)",
            tie_break_method="history",
        ),
        # Tier 2 (Tests - Medium Confidence via Heuristics)
        ScoredFileEntry(
            path="tests/test_api.py",
            tier_index=2,
            confidence="medium",
            confidence_reason="topology + domain heuristic tie-break",
            tie_break_method="heuristic",
        ),
        # Isolated Files (Low Confidence)
        ScoredFileEntry(
            path="docs/index.md",
            tier_index=-1,
            confidence="low",
            confidence_reason="isolated, no internal dependency signal",
            tie_break_method="none",
        ),
    ]

    summary = RepoConfidenceSummary(
        high_pct=33.33,
        medium_pct=16.67,
        low_pct=50.00,
        history_available=True,
    )

    return ScoredOrderingResult(
        files=files,
        repo_confidence_summary=summary,
        isolated_files=["docs/index.md"],
        cyclic_files=["src/app.py", "src/routes.py"],
    )


def test_stage_d_system_prompt_principles():
    """Validates that STAGE_D_SYSTEM_PROMPT contains essential pedagogical and anti-hallucination rules."""
    assert "Senior Software Architect" in STAGE_D_SYSTEM_PROMPT
    assert "HONEST CONFIDENCE CALIBRATION" in STAGE_D_SYSTEM_PROMPT
    assert "Cyclic Clusters" in STAGE_D_SYSTEM_PROMPT
    assert "DO NOT HALLUCINATE" in STAGE_D_SYSTEM_PROMPT


def test_user_prompt_construction(sample_scored_result):
    """Verifies that the generated LLM user prompt contains all tier indices, files, confidence tags, and cyclic flags."""
    engine = NarrationEngine()
    prompt = engine._build_user_prompt(sample_scored_result)

    assert "Total Scored Files: 6" in prompt
    assert "High=33.33%, Medium=16.67%, Low=50.0%" in prompt
    assert "Milestone 1 (Tier 0):" in prompt
    assert "`src/config.py` | Confidence: HIGH" in prompt
    assert "Milestone 2 (Tier 1) [CYCLIC CLUSTER]:" in prompt
    assert "`src/app.py` | Confidence: LOW" in prompt
    assert "Milestone 3 (Tier 2):" in prompt
    assert "`tests/test_api.py` | Confidence: MEDIUM" in prompt
    assert "Isolated Standalone Files (Tier -1):" in prompt
    assert "`docs/index.md`" in prompt


def test_calibrated_confidence_disclosure_with_history(sample_scored_result):
    """Verifies calibrated honesty disclosure when Git history is present."""
    engine = NarrationEngine()
    disclosure = engine._build_confidence_disclosure(sample_scored_result)

    assert "6 Scored Files" in disclosure
    assert "33.33% High Confidence" in disclosure
    assert "verified Git commit timestamps" in disclosure
    assert "16.67% Medium Confidence" in disclosure
    assert "domain precedence rules" in disclosure
    assert "2 Files in Cycles" in disclosure
    assert "1 Standalone Files" in disclosure


def test_calibrated_confidence_disclosure_no_history():
    """Verifies calibrated honesty disclosure when Git history is absent (zip upload)."""
    files = [
        ScoredFileEntry(
            path="main.py",
            tier_index=0,
            confidence="medium",
            confidence_reason="topology + domain heuristic tie-break",
            tie_break_method="heuristic",
        )
    ]
    summary = RepoConfidenceSummary(
        high_pct=0.0,
        medium_pct=100.0,
        low_pct=0.0,
        history_available=False,
    )
    scored_result = ScoredOrderingResult(
        files=files,
        repo_confidence_summary=summary,
        isolated_files=[],
        cyclic_files=[],
    )

    engine = NarrationEngine()
    disclosure = engine._build_confidence_disclosure(scored_result)

    assert "No Git History / Zip Upload" in disclosure
    assert "build order was estimated from how files import each other rather than when they were actually written" in disclosure


def test_deterministic_narration_fallback(sample_scored_result):
    """Verifies that deterministic narration generation creates structured milestones and explanations."""
    engine = NarrationEngine()
    result = engine.generate_narration(sample_scored_result, llm_provider=None)

    assert len(result.steps) == 3
    # Step 1 (Tier 0)
    step1 = result.steps[0]
    assert step1.step_number == 1
    assert step1.tier_index == 0
    assert "Foundation" in step1.title
    assert step1.dominant_confidence == "high"
    assert "src/config.py" in step1.files
    assert "src/constants.py" in step1.files
    assert not step1.is_cyclic_cluster

    # Step 2 (Tier 1) - Cyclic
    step2 = result.steps[1]
    assert step2.step_number == 2
    assert step2.tier_index == 1
    assert step2.is_cyclic_cluster
    assert step2.dominant_confidence == "low"
    assert "circular dependency cluster" in step2.pedagogical_explanation

    # Step 3 (Tier 2) - Tests
    step3 = result.steps[2]
    assert step3.step_number == 3
    assert step3.tier_index == 2
    assert "tests/test_api.py" in step3.files

    # Standalone files
    assert "docs/index.md" in result.isolated_files_summary


def test_llm_provider_execution(sample_scored_result):
    """Verifies LLM provider invocation and graceful handling."""
    called_prompts = []

    def mock_llm(sys_prompt: str, user_prompt: str) -> str:
        called_prompts.append((sys_prompt, user_prompt))
        return "# Custom LLM Architectural Narrative\nStep 1: Start with config."

    engine = NarrationEngine()
    result = engine.generate_narration(sample_scored_result, llm_provider=mock_llm)

    assert len(called_prompts) == 1
    assert "Senior Software Architect" in called_prompts[0][0]
    assert "Total Scored Files: 6" in called_prompts[0][1]
    assert "Custom LLM Architectural Narrative" in result.overview
    assert len(result.steps) == 3


def test_llm_provider_exception_fallback(sample_scored_result):
    """Verifies that if the LLM provider raises an exception, deterministic fallback completes cleanly."""
    def failing_llm(sys_prompt: str, user_prompt: str) -> str:
        raise RuntimeError("API timeout / Rate limit")

    engine = NarrationEngine()
    result = engine.generate_narration(sample_scored_result, llm_provider=failing_llm)

def test_anti_hallucination_co_tiered_siblings_not_falsely_coupled(sample_scored_result):
    """
    Verifies that co-tiered sibling files (e.g. src/config.py and src/constants.py in Tier 0)
    are NOT asserted to depend on one another, but are correctly framed as independent foundations.
    """
    engine = NarrationEngine()
    result = engine.generate_narration(sample_scored_result, llm_provider=None)

    step0 = result.steps[0]
    # Check that it states they depend on zero internal project modules
    assert "zero internal dependencies" in step0.pedagogical_explanation
    # Check that it does not claim config depends on constants or vice-versa
    assert "depends on `src/constants.py`" not in step0.pedagogical_explanation
    assert "depends on `src/config.py`" not in step0.pedagogical_explanation
    assert "2/2 files verified via Git history" in step0.pedagogical_explanation


def test_cyclic_cluster_explicit_non_ordinal_framing(sample_scored_result):
    """
    Verifies that the cyclic cluster milestone explicitly instructs studying files as a cohesive unit
    and forbids false linear ordering.
    """
    engine = NarrationEngine()
    result = engine.generate_narration(sample_scored_result, llm_provider=None)

    cyclic_step = [s for s in result.steps if s.is_cyclic_cluster][0]
    assert "circular dependency cluster" in cyclic_step.pedagogical_explanation
    assert "cohesive subsystem rather than in a strict linear order" in cyclic_step.pedagogical_explanation
    assert "2/2 co-dependent files in a circular cluster" in cyclic_step.pedagogical_explanation


def test_domain_segregation_and_confidence_breakdown(sample_scored_result):
    """
    Verifies that multi-domain tiers cleanly segregate core, examples, and tests into domain groups,
    and that confidence_breakdown captures the exact counts without loss.
    """
    engine = NarrationEngine()
    result = engine.generate_narration(sample_scored_result, llm_provider=None)

    step0 = result.steps[0]
    # Check domain groups populated
    assert "core" in step0.domain_groups
    assert step0.confidence_breakdown == {"high": 2}

    # Step 1 (cyclic)
    step1 = result.steps[1]
    assert step1.confidence_breakdown == {"low": 2}

    # Verify no fan-in blanket overclaims exist across any step
    for step in result.steps:
        assert "all subsequent layers rely" not in step.pedagogical_explanation
        assert "everything depends on" not in step.pedagogical_explanation


