"""Unit tests for Layer 6 (Stage B) Constrained Tie-Breaking Within Tiers."""

import pytest
from app.models.history import CommitHistoryResult, FirstAppearance
from app.parser.schema import FileNode, ImportEdge
from app.sequence.baseline_ordering import BaselineOrderingEngine
from app.sequence.constrained_tie_breaking import ConstrainedTieBreakerEngine
from app.sequence.schema import BaselineOrderingResult, NodeMetadata, Tier


def test_history_based_tie_breaking():
    """
    Acceptance Criteria 1:
    A tier where reliable git history exists is fully ordered via history alone,
    with zero LLM calls made.
    """
    baseline = BaselineOrderingResult(
        tiers=[Tier(tier_index=0, files=["b_file.py", "a_file.py"])],
        node_metadata={
            "a_file.py": NodeMetadata(path="a_file.py", domain="backend"),
            "b_file.py": NodeMetadata(path="b_file.py", domain="backend"),
        },
    )

    history = CommitHistoryResult(
        history_available=True,
        history_confidence="high",
        file_first_appearance={
            "b_file.py": FirstAppearance(commit_hash="c1", timestamp="2026-01-01T00:00:00Z"),
            "a_file.py": FirstAppearance(commit_hash="c2", timestamp="2026-01-02T00:00:00Z"),
        },
    )

    llm_called = False

    def dummy_llm(tied_files, file_contents, node_metadata):
        nonlocal llm_called
        llm_called = True
        return (tied_files, "llm reasoning")

    engine = ConstrainedTieBreakerEngine()
    result = engine.refine_baseline_order(
        baseline_result=baseline,
        commit_history=history,
        llm_provider=dummy_llm,
    )

    assert llm_called is False
    assert len(result.tiers) == 1
    tier = result.tiers[0]
    assert len(tier.ordered_files) == 2

    # b_file.py was created earlier (2026-01-01) than a_file.py (2026-01-02)
    assert tier.ordered_files[0].path == "b_file.py"
    assert tier.ordered_files[0].tie_break_method == "history"

    assert tier.ordered_files[1].path == "a_file.py"
    assert tier.ordered_files[1].tie_break_method == "history"


def test_heuristic_based_tie_breaking():
    """
    Acceptance Criteria 2:
    A tier with no history but a clear domain-heuristic signal (e.g. config vs backend)
    is ordered via heuristics, not the LLM.
    """
    baseline = BaselineOrderingResult(
        tiers=[Tier(tier_index=0, files=["routes.py", "settings.py"])],
        node_metadata={
            "routes.py": NodeMetadata(path="routes.py", domain="backend"),
            "settings.py": NodeMetadata(path="settings.py", domain="config"),
        },
    )

    llm_called = False

    def dummy_llm(tied_files, file_contents, node_metadata):
        nonlocal llm_called
        llm_called = True
        return (tied_files, "llm reasoning")

    engine = ConstrainedTieBreakerEngine()
    result = engine.refine_baseline_order(
        baseline_result=baseline,
        commit_history=None,
        llm_provider=dummy_llm,
    )

    assert llm_called is False
    assert len(result.tiers) == 1
    tier = result.tiers[0]

    # settings.py (config, priority 1) precedes routes.py (backend, priority 4)
    assert tier.ordered_files[0].path == "settings.py"
    assert tier.ordered_files[0].tie_break_method == "heuristic"

    assert tier.ordered_files[1].path == "routes.py"
    assert tier.ordered_files[1].tie_break_method == "heuristic"


def test_llm_based_tie_breaking():
    """
    Acceptance Criteria 3:
    A tier requiring genuine LLM judgment produces a result, with each file's reasoning captured.
    """
    baseline = BaselineOrderingResult(
        tiers=[Tier(tier_index=0, files=["user_service.py", "auth_service.py"])],
        node_metadata={
            "user_service.py": NodeMetadata(path="user_service.py", domain="backend"),
            "auth_service.py": NodeMetadata(path="auth_service.py", domain="backend"),
        },
    )

    def mock_llm(tied_files, file_contents, node_metadata):
        # LLM proposes auth_service before user_service
        return (["auth_service.py", "user_service.py"], "Auth logic is foundational to User management")

    engine = ConstrainedTieBreakerEngine()
    result = engine.refine_baseline_order(
        baseline_result=baseline,
        commit_history=None,
        llm_provider=mock_llm,
    )

    assert len(result.tiers) == 1
    tier = result.tiers[0]

    assert tier.ordered_files[0].path == "auth_service.py"
    assert tier.ordered_files[0].tie_break_method == "llm"
    assert tier.ordered_files[0].reasoning == "Auth logic is foundational to User management"

    assert tier.ordered_files[1].path == "user_service.py"
    assert tier.ordered_files[1].tie_break_method == "llm"


def test_adversarial_cross_tier_violation_rejection():
    """
    Acceptance Criteria 4 (Adversarial Test - Highest Priority):
    Construct a case where the LLM is deliberately prompted/tempted to suggest moving a file to a different tier.
    Confirm the validation step catches and rejects this, keeping the file in its original tier.
    """
    baseline = BaselineOrderingResult(
        tiers=[
            Tier(tier_index=0, files=["schema.py"]),
            Tier(tier_index=1, files=["service_a.py", "service_b.py"]),
        ],
        node_metadata={
            "schema.py": NodeMetadata(path="schema.py", domain="database"),
            "service_a.py": NodeMetadata(path="service_a.py", domain="backend"),
            "service_b.py": NodeMetadata(path="service_b.py", domain="backend"),
        },
    )

    # Adversarial LLM proposes moving 'schema.py' (from Tier 0) into Tier 1!
    def adversarial_llm(tied_files, file_contents, node_metadata):
        return (["schema.py", "service_a.py", "service_b.py"], "Schema should be built with services")

    engine = ConstrainedTieBreakerEngine()
    result = engine.refine_baseline_order(
        baseline_result=baseline,
        commit_history=None,
        llm_provider=adversarial_llm,
    )

    # Tier 0 (schema.py) should be unchanged
    assert result.tiers[0].ordered_files[0].path == "schema.py"

    # Tier 1 proposal was invalid (included schema.py from Tier 0) -> REJECTED!
    tier_1 = result.tiers[1]
    assert set(f.path for f in tier_1.ordered_files) == {"service_a.py", "service_b.py"}
    for entry in tier_1.ordered_files:
        assert entry.tie_break_method == "unresolved"
        assert entry.reasoning is None


def test_unresolved_fallback():
    """
    Acceptance Criteria 5:
    A tier where none of the three methods produce a confident order stays tied,
    marked "unresolved", rather than being forced into an arbitrary sequence.
    """
    baseline = BaselineOrderingResult(
        tiers=[Tier(tier_index=0, files=["mod_x.py", "mod_y.py"])],
        node_metadata={
            "mod_x.py": NodeMetadata(path="mod_x.py", domain="backend"),
            "mod_y.py": NodeMetadata(path="mod_y.py", domain="backend"),
        },
    )

    # History confidence reduced, no LLM provider
    history = CommitHistoryResult(
        history_available=True,
        history_confidence="reduced",
        file_first_appearance={},
    )

    engine = ConstrainedTieBreakerEngine()
    result = engine.refine_baseline_order(
        baseline_result=baseline,
        commit_history=history,
        llm_provider=None,
    )

    assert len(result.tiers) == 1
    tier = result.tiers[0]
    assert len(tier.ordered_files) == 2
    for entry in tier.ordered_files:
        assert entry.tie_break_method == "unresolved"


def test_stage_b_refinement_on_stage_a_output():
    """
    Integration test refining real Stage A baseline ordering output.
    """
    node_c = FileNode(path="config.py", language="python", imports=[])
    node_b = FileNode(
        path="backend.py",
        language="python",
        imports=[ImportEdge(target="config.py", source_path="backend.py", resolved=True, is_external=False)],
    )
    node_f = FileNode(
        path="frontend.py",
        language="python",
        imports=[ImportEdge(target="config.py", source_path="frontend.py", resolved=True, is_external=False)],
    )

    stage_a_engine = BaselineOrderingEngine()
    baseline = stage_a_engine.compute_baseline_order([node_c, node_b, node_f])

    # Tier 0: config.py
    # Tier 1: backend.py and frontend.py (both depend on config.py)
    assert len(baseline.tiers) == 2

    # Set metadata domains
    baseline.node_metadata["config.py"].domain = "config"
    baseline.node_metadata["backend.py"].domain = "backend"
    baseline.node_metadata["frontend.py"].domain = "frontend"

    stage_b_engine = ConstrainedTieBreakerEngine()
    refined = stage_b_engine.refine_baseline_order(baseline)

    assert len(refined.tiers) == 2
    tier_1 = refined.tiers[1]

    # Heuristics resolve Tier 1: backend (priority 4) < frontend (priority 5)
    assert tier_1.ordered_files[0].path == "backend.py"
    assert tier_1.ordered_files[0].tie_break_method == "heuristic"

    assert tier_1.ordered_files[1].path == "frontend.py"
    assert tier_1.ordered_files[1].tie_break_method == "heuristic"


def test_history_tie_breaking_with_partial_timestamp_collisions():
    """
    Bug B Validation:
    When a tier contains some files with distinct timestamps and some files with
    identical co-committed timestamps, history tie-breaking should NOT be discarded
    for the entire tier. Distinct files get tie_break_method='history', while the
    co-committed subgroup is refined via heuristics.
    """
    baseline = BaselineOrderingResult(
        tiers=[Tier(tier_index=0, files=["a_early.py", "b_mid1.py", "c_mid2.py", "d_late.py"])],
        node_metadata={
            "a_early.py": NodeMetadata(path="a_early.py", domain="backend"),
            "b_mid1.py": NodeMetadata(path="b_mid1.py", domain="config"),  # prio 1
            "c_mid2.py": NodeMetadata(path="c_mid2.py", domain="backend"), # prio 4
            "d_late.py": NodeMetadata(path="d_late.py", domain="backend"),
        },
    )

    # a_early is 2020-01-01, b_mid1 & c_mid2 are both 2021-06-01 (tied), d_late is 2022-01-01
    history = CommitHistoryResult(
        history_available=True,
        history_confidence="high",
        file_first_appearance={
            "a_early.py": FirstAppearance(commit_hash="c1", timestamp="2020-01-01T00:00:00Z"),
            "b_mid1.py": FirstAppearance(commit_hash="c2", timestamp="2021-06-01T00:00:00Z"),
            "c_mid2.py": FirstAppearance(commit_hash="c2", timestamp="2021-06-01T00:00:00Z"),
            "d_late.py": FirstAppearance(commit_hash="c3", timestamp="2022-01-01T00:00:00Z"),
        },
    )

    engine = ConstrainedTieBreakerEngine()
    result = engine.refine_baseline_order(baseline, commit_history=history)

    assert len(result.tiers) == 1
    ordered = result.tiers[0].ordered_files
    assert len(ordered) == 4

    # 1. a_early.py was earliest (2020) -> history
    assert ordered[0].path == "a_early.py"
    assert ordered[0].tie_break_method == "history"

    # 2. b_mid1.py and c_mid2.py (2021) -> heuristic (config < backend)
    assert ordered[1].path == "b_mid1.py"
    assert ordered[1].tie_break_method == "heuristic"
    assert ordered[2].path == "c_mid2.py"
    assert ordered[2].tie_break_method == "heuristic"

    # 3. d_late.py was latest (2022) -> history
    assert ordered[3].path == "d_late.py"
    assert ordered[3].tie_break_method == "history"

