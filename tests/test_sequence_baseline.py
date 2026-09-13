"""Unit tests for Layer 6 (Stage A) Deterministic Baseline Ordering & Cycle Handling."""

import pytest
from app.parser.schema import FileNode, ImportEdge, ImportCategory
from app.segmentation.schema import ClassificationMethod, ConfidenceLevel, DomainType, SegmentedFileNode, SegmentationResult
from app.sequence.baseline_ordering import BaselineOrderingEngine
from app.sequence.schema import BaselineOrderingResult, Tier, NodeMetadata


def test_linear_dependency_chain():
    """
    Test simple linear chain: A imports B, B imports C (A depends on B, B depends on C).
    Expected build order tiers:
      Tier 0: [C] (prerequisites: none)
      Tier 1: [B] (prerequisites: C)
      Tier 2: [A] (prerequisites: B)
    """
    engine = BaselineOrderingEngine()

    node_c = FileNode(path="c.py", language="python", imports=[])
    node_b = FileNode(
        path="b.py",
        language="python",
        imports=[
            ImportEdge(
                target="c.py",
                source_path="b.py",
                resolved=True,
                is_external=False,
            )
        ],
    )
    node_a = FileNode(
        path="a.py",
        language="python",
        imports=[
            ImportEdge(
                target="b.py",
                source_path="a.py",
                resolved=True,
                is_external=False,
            )
        ],
    )

    result = engine.compute_baseline_order([node_a, node_b, node_c])

    assert len(result.tiers) == 3
    assert result.tiers[0].tier_index == 0
    assert result.tiers[0].files == ["c.py"]
    assert result.tiers[0].is_cyclic_cluster is False

    assert result.tiers[1].tier_index == 1
    assert result.tiers[1].files == ["b.py"]
    assert result.tiers[1].is_cyclic_cluster is False

    assert result.tiers[2].tier_index == 2
    assert result.tiers[2].files == ["a.py"]
    assert result.tiers[2].is_cyclic_cluster is False

    assert result.isolated_files == []
    assert result.cyclic_files == []


def test_genuine_cycle_detection():
    """
    Test circular dependency: A imports B, B imports A (A ↔ B).
    Expected:
      - 1 tier containing ['a.py', 'b.py'] with is_cyclic_cluster = True
      - cyclic_files = ['a.py', 'b.py']
    """
    engine = BaselineOrderingEngine()

    node_a = FileNode(
        path="a.py",
        language="python",
        imports=[
            ImportEdge(
                target="b.py",
                source_path="a.py",
                resolved=True,
                is_external=False,
            )
        ],
    )
    node_b = FileNode(
        path="b.py",
        language="python",
        imports=[
            ImportEdge(
                target="a.py",
                source_path="b.py",
                resolved=True,
                is_external=False,
            )
        ],
    )

    result = engine.compute_baseline_order([node_a, node_b])

    assert len(result.tiers) == 1
    assert result.tiers[0].is_cyclic_cluster is True
    assert set(result.tiers[0].files) == {"a.py", "b.py"}
    assert set(result.cyclic_files) == {"a.py", "b.py"}
    assert result.isolated_files == []


def test_isolated_files_identification():
    """
    Test files with zero internal dependency edges in or out.
    """
    engine = BaselineOrderingEngine()

    node_core = FileNode(path="core.py", language="python", imports=[])
    node_app = FileNode(
        path="app.py",
        language="python",
        imports=[
            ImportEdge(
                target="core.py",
                source_path="app.py",
                resolved=True,
                is_external=False,
            )
        ],
    )
    node_isolated1 = FileNode(path="standalone.py", language="python", imports=[])
    node_isolated2 = FileNode(path="unused.py", language="python", imports=[])

    result = engine.compute_baseline_order(
        [node_core, node_app, node_isolated1, node_isolated2]
    )

    assert result.isolated_files == ["standalone.py", "unused.py"]
    assert len(result.tiers) == 2
    assert result.tiers[0].files == ["core.py"]
    assert result.tiers[1].files == ["app.py"]


def test_mixed_graph_topology():
    """
    Test graph combining linear chain (A imports B, B imports C), cycle (D ↔ E, where D imports C), and isolated file Z.
    """
    engine = BaselineOrderingEngine()

    node_c = FileNode(path="c.py", language="python", imports=[])
    node_b = FileNode(
        path="b.py",
        language="python",
        imports=[ImportEdge(target="c.py", source_path="b.py", resolved=True, is_external=False)],
    )
    node_a = FileNode(
        path="a.py",
        language="python",
        imports=[ImportEdge(target="b.py", source_path="a.py", resolved=True, is_external=False)],
    )

    # Cycle D ↔ E, D also depends on C
    node_d = FileNode(
        path="d.py",
        language="python",
        imports=[
            ImportEdge(target="e.py", source_path="d.py", resolved=True, is_external=False),
            ImportEdge(target="c.py", source_path="d.py", resolved=True, is_external=False),
        ],
    )
    node_e = FileNode(
        path="e.py",
        language="python",
        imports=[ImportEdge(target="d.py", source_path="e.py", resolved=True, is_external=False)],
    )

    node_z = FileNode(path="z.py", language="python", imports=[])

    result = engine.compute_baseline_order([node_a, node_b, node_c, node_d, node_e, node_z])

    assert result.isolated_files == ["z.py"]
    assert set(result.cyclic_files) == {"d.py", "e.py"}

    # C is tier 0
    assert result.tiers[0].files == ["c.py"]

    # At tier 1, both 'b.py' and cycle '{d.py, e.py}' depend on 'c.py'
    tier_1_files = set()
    for t in result.tiers[1:]:
        if t.is_cyclic_cluster:
            assert set(t.files) == {"d.py", "e.py"}
        else:
            tier_1_files.update(t.files)

    assert "b.py" in tier_1_files or "a.py" in tier_1_files


def test_unresolved_and_external_edges_ignored():
    """
    Verify that unresolved (resolved=False) and external (is_external=True) edges do not inform internal build tiers.
    """
    engine = BaselineOrderingEngine()

    node_x = FileNode(
        path="x.py",
        language="python",
        imports=[
            # External edge
            ImportEdge(target="requests", source_path="x.py", resolved=True, is_external=True),
            # Unresolved edge
            ImportEdge(target="unknown_mod.py", source_path="x.py", resolved=False, is_external=False),
        ],
    )

    result = engine.compute_baseline_order([node_x])

    # x.py has no resolved internal edges -> isolated file
    assert result.isolated_files == ["x.py"]
    assert len(result.tiers) == 0


def test_segmentation_metadata_attached():
    """
    Verify Layer 4 domain metadata is attached to NodeMetadata output.
    """
    engine = BaselineOrderingEngine()

    node_a = FileNode(path="src/app.py", language="python", imports=[])

    seg_result = SegmentationResult(
        files=[
            SegmentedFileNode(
                path="src/app.py",
                domain=DomainType.BACKEND,
                classification_method=ClassificationMethod.CONVENTION,
                confidence=ConfidenceLevel.HIGH,
            )
        ]
    )

    result = engine.compute_baseline_order([node_a], segmentation_result=seg_result)

    meta = result.node_metadata.get("src/app.py")
    assert meta is not None
    assert meta.domain == "backend"
