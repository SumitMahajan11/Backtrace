"""Tests for dependency edge deduplication and imported-by resolution."""

import pytest
from app.formatters.graph_formatter import GraphExportFormatter, dedupe_edges, imported_by
from app.parser.python_parser import PythonLanguageParser
from app.parser.schema import FileNode
from app.segmentation.schema import SegmentationResult, SegmentedFileNode, DomainType, ClassificationMethod, ConfidenceLevel
from app.sequence.schema import SequenceNarrationResult, BuildStepNarrative
from app.synthesis.engine import SynthesisEngine


def test_dependency_edge_deduplication():
    """Test: a fixture where a.py imports b.py three times yields imported_by(b) == ['a.py'] and total edges == 1."""
    a_code = """
import b
from b import helper1
from b import helper2
"""
    b_code = """
def helper1():
    pass

def helper2():
    pass
"""
    all_files = {"a.py", "b.py"}
    parser = PythonLanguageParser()

    node_a, edges_a = parser.parse_single_file("a.py", a_code, all_files)
    node_b, edges_b = parser.parse_single_file("b.py", b_code, all_files)

    # 1. Verify parser-level deduplication
    assert len(edges_a) == 1
    assert edges_a[0].target == "b.py"
    assert edges_a[0].source_path == "a.py"

    # 2. Verify imported_by helper on raw edges
    assert imported_by("b.py", edges_a) == ["a.py"]

    # 3. Verify synthesis engine deduplication
    seg_res = SegmentationResult(
        files=[
            SegmentedFileNode(path="a.py", domain=DomainType.CORE, classification_method=ClassificationMethod.CONVENTION, confidence=ConfidenceLevel.HIGH),
            SegmentedFileNode(path="b.py", domain=DomainType.CORE, classification_method=ClassificationMethod.CONVENTION, confidence=ConfidenceLevel.HIGH),
        ],
        domain_counts={"core": 2},
        method_counts={"convention": 2},
    )
    narration_res = SequenceNarrationResult(
        overview="Overview",
        confidence_disclosure="Disclosure",
        steps=[
            BuildStepNarrative(
                step_number=1,
                title="Step 1",
                tier_index=0,
                files=["b.py", "a.py"],
                dominant_domain="core",
                dominant_confidence="high",
                pedagogical_explanation="Foundation",
            )
        ],
        isolated_files_summary="",
    )

    synthesis_engine = SynthesisEngine()
    report = synthesis_engine.synthesize(
        repo_name="test_repo",
        segmentation_result=seg_res,
        narration_result=narration_res,
        parsed_files=[node_a, node_b],
        file_contents={"a.py": a_code, "b.py": b_code},
    )

    # In report, file_dependencies must be deduped
    assert len(report.file_dependencies) == 1
    assert report.file_dependencies[0]["source"] == "a.py"
    assert report.file_dependencies[0]["target"] == "b.py"

    # 4. Verify graph formatter DAG output
    graph_formatter = GraphExportFormatter()
    dag = graph_formatter.format_json_dag(report)

    # Total edges must be exactly 1
    total_edges = len(dag["edges"])
    assert total_edges == 1

    # imported_by(b) yields ["a.py"]
    b_importers = imported_by("b.py", dag["edges"])
    assert b_importers == ["a.py"]

    # Dedupe helper directly handles duplicate dictionary lists
    raw_dup_edges = [
        {"source": "a.py", "target": "b.py"},
        {"source": "a.py", "target": "b.py"},
        {"source": "a.py", "target": "b.py"},
    ]
    deduped = dedupe_edges(raw_dup_edges)
    assert len(deduped) == 1
    assert imported_by("b.py", deduped) == ["a.py"]
