"""Live LLM Narration & Guardrail Verification Suite.

Tests structured LLM response parsing and executes real LLM generation
against pallets/flask (83 files) to scrutinize:
1. Non-ordinal framing on cyclic clusters.
2. Anti-hallucination / groundedness against repo AST facts.
3. Citation fidelity.
"""

import json
from pathlib import Path
import pytest

from app.orchestration.pipeline import PipelineOrchestrator
from app.sequence.narration_engine import NarrationEngine
from app.sequence.llm_client import create_ollama_provider, get_default_llm_provider
from app.sequence.schema import ScoredFileEntry, ScoredOrderingResult, RepoConfidenceSummary


def test_structured_llm_response_parsing():
    """
    Verifies that NarrationEngine._parse_or_wrap_llm_response properly parses
    raw LLM markdown blocks into BuildStepNarrative.pedagogical_explanation and title,
    while strictly preserving AST files, domain groups, and confidence breakdowns.
    """
    scored = ScoredOrderingResult(
        files=[
            ScoredFileEntry(path="a.py", tier_index=0, confidence="high", confidence_reason="No tie", tie_break_method="none"),
            ScoredFileEntry(path="b.py", tier_index=1, confidence="low", confidence_reason="Cyclic dependency", tie_break_method="none"),
            ScoredFileEntry(path="c.py", tier_index=1, confidence="low", confidence_reason="Cyclic dependency", tie_break_method="none"),
        ],
        repo_confidence_summary=RepoConfidenceSummary(
            high_pct=33.33, medium_pct=0.0, low_pct=66.67, history_available=True
        ),
        cyclic_files=["b.py", "c.py"],
        isolated_files=[],
    )

    raw_llm_markdown = """# Architecture Overview
This is a micro-system demonstrating core primitives and a circular engine.

### Milestone 1: Leaf Foundation Primitives
**Role:** Implement `a.py` as an isolated entrypoint with zero internal dependencies.

### Milestone 2: Cyclic Core Subsystem
**Role:** Study and build `b.py` and `c.py` together as a co-dependent subsystem. Because these modules share circular references, they should be understood as an interconnected unit rather than sequentially.
"""

    engine = NarrationEngine()
    result = engine._parse_or_wrap_llm_response(
        raw_response=raw_llm_markdown,
        scored_result=scored,
        refined_result=None,
        disclosure="Disclosure note",
        prompt_used="User prompt",
    )

    assert len(result.steps) == 2
    
    # Milestone 1 assertions
    s1 = result.steps[0]
    assert s1.step_number == 1
    assert "Leaf Foundation Primitives" in s1.title
    assert "Implement `a.py` as an isolated entrypoint" in s1.pedagogical_explanation
    assert s1.files == ["a.py"]
    assert s1.dominant_confidence == "high"

    # Milestone 2 assertions (Cyclic)
    s2 = result.steps[1]
    assert s2.step_number == 2
    assert "Cyclic Core Subsystem" in s2.title
    assert "Study and build `b.py` and `c.py` together as a co-dependent subsystem" in s2.pedagogical_explanation
    assert s2.is_cyclic_cluster is True
    assert s2.files == ["b.py", "c.py"]
    assert s2.dominant_confidence == "low"


def test_milestone_prose_validation_defense():
    """
    Verifies that _validate_milestone_prose detects and strips cross-milestone file
    hallucinations and safely falls back if the explanation is contaminated.
    """
    engine = NarrationEngine()
    milestone_files = ["src/flask/signals.py", "src/flask/typing.py"]
    fallback = "Fallback deterministic explanation."

    # Case 1: Grounded prose - all files are in milestone
    valid_prose = "Implements signal handling in `src/flask/signals.py` and typing contracts in `src/flask/typing.py`."
    res1, stripped1, used_fb1 = engine._validate_milestone_prose(valid_prose, milestone_files, fallback)
    assert res1 == valid_prose
    assert stripped1 == 0
    assert used_fb1 is False

    # Case 2: Mixed prose with discourse connective healing
    mixed_prose = (
        "This milestone establishes the foundational type contracts in `src/flask/typing.py` and signal infrastructure. "
        "Furthermore, it configures celery dispatching via `examples/celery/make_celery.py` for asynchronous task execution. "
        "Additionally, it ensures core leaf utilities can communicate across decoupled application components."
    )
    res2, stripped2, used_fb2 = engine._validate_milestone_prose(mixed_prose, milestone_files, fallback)
    assert "src/flask/typing.py" in res2
    assert "make_celery.py" not in res2
    assert "Furthermore" not in res2
    assert "Additionally" not in res2
    assert "It ensures core leaf utilities can communicate" in res2
    assert stripped2 == 1
    assert used_fb2 is False

    # Case 3: Sentence splitting robustness on abbreviations like 'e.g.'
    abbrev_prose = (
        "This milestone introduces basic leaf utilities, e.g. `src/flask/signals.py` for lightweight event dispatching. "
        "It provides clean event hooks without incurring circular dependencies."
    )
    res_abbrev, stripped_a, used_fb_a = engine._validate_milestone_prose(abbrev_prose, milestone_files, fallback)
    assert stripped_a == 0
    assert used_fb_a is False
    assert "e.g. `src/flask/signals.py`" in res_abbrev

    # Case 4: Minimal length guardrail (<15 words falls back to deterministic)
    stub_prose = "Valid `src/flask/signals.py`."
    res_stub, stripped_s, used_fb_s = engine._validate_milestone_prose(stub_prose, milestone_files, fallback)
    assert res_stub == fallback
    assert used_fb_s is True

    # Case 5: Totally compromised prose - all sentences hallucinate out-of-milestone files
    bad_prose = "Demonstrates celery integration via `examples/celery/make_celery.py`."
    res3, stripped3, used_fb3 = engine._validate_milestone_prose(bad_prose, milestone_files, fallback)
    assert res3 == fallback
    assert stripped3 == 1
    assert used_fb3 is True


def test_live_ollama_flask_narration():
    """
    Executes live Ollama generation on pallets/flask (83 files) using local llama3.2:3b.
    Scrutinizes generated pedagogical prose for:
    - LLM presence (different from offline template).
    - Cyclic cluster framing (Tier 1).
    - Fidelity to actual repository files.
    """
    provider = get_default_llm_provider()
    if provider is None:
        pytest.skip("Local Ollama daemon not running or model unavailable")

    cache_path = Path(__file__).resolve().parent / "fixtures" / "flask_cache.json"
    assert cache_path.exists()
    with open(cache_path, "r", encoding="utf-8") as f:
        cache_data = json.load(f)
    flask_contents = cache_data["code_contents"]

    orchestrator = PipelineOrchestrator()
    res = orchestrator.run_pipeline(
        repo_name="pallets/flask",
        file_paths=list(flask_contents.keys()),
        file_contents=flask_contents,
        enable_rag=True,
        llm_provider=provider,
    )

    assert res.success is True
    report = res.report
    assert report is not None

    # Write the full markdown report to file for detailed review
    out_md = Path(__file__).resolve().parent.parent / "live_llm_report.md"
    out_md.write_text(res.markdown_output, encoding="utf-8")
    print(f"\n[Saved full live LLM report to {out_md}]")

    # Check overview
    assert len(report.architecture_overview.domain_file_counts) > 0

    for m in report.milestones:
        print("\n" + "=" * 60)
        print(f"MILESTONE {m.tier}: {m.title} (Cyclic: {m.is_cyclic}, Confidence: {m.confidence_breakdown})")
        print(f"Summary:\n{m.summary}")
        if m.deep_dive_citations:
            print(f"Citations count: {len(m.deep_dive_citations)}")
            for c in m.deep_dive_citations[:3]:
                print(f"  - {c}")
        print("=" * 60)
