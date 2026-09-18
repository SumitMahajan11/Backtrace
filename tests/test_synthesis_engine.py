"""Unit tests for Layer 7 Synthesis Engine."""

import pytest
from app.parser.schema import FileNode
from app.rag.engine import HybridRAGEngine
from app.segmentation.schema import (
    ClassificationMethod,
    ConfidenceLevel,
    DomainType,
    SegmentedFileNode,
    SegmentationResult,
)
from app.sequence.schema import (
    ScoredOrderingResult,
    ScoredFileEntry,
    RepoConfidenceSummary,
    RefinedOrderingResult,
    RefinedTier,
    FileOrderEntry,
    NodeMetadata,
)
from app.sequence.narration_engine import NarrationEngine
from app.synthesis.engine import SynthesisEngine


def test_synthesis_engine_report_generation():
    # 1. Mock parsed files
    file1 = FileNode(path="src/core.py", language="python", entry_point=True, exports=["CoreApp"])
    file2 = FileNode(path="src/utils.py", language="python", exports=["helper_fn"])
    file3 = FileNode(path="tests/test_core.py", language="python", exports=[])

    # 2. Mock segmentation result
    seg_res = SegmentationResult(
        files=[
            SegmentedFileNode(path="src/core.py", domain=DomainType.CORE, classification_method=ClassificationMethod.CONVENTION, confidence=ConfidenceLevel.HIGH),
            SegmentedFileNode(path="src/utils.py", domain=DomainType.BACKEND, classification_method=ClassificationMethod.CONVENTION, confidence=ConfidenceLevel.HIGH),
            SegmentedFileNode(path="tests/test_core.py", domain=DomainType.TESTS, classification_method=ClassificationMethod.CONVENTION, confidence=ConfidenceLevel.HIGH),
        ],
        domain_counts={"core": 1, "backend": 1, "tests": 1},
        method_counts={"convention": 3},
    )

    # 3. Mock confidence scored sequence
    scored_seq = ScoredOrderingResult(
        files=[
            ScoredFileEntry(path="src/utils.py", tier_index=0, confidence="high", confidence_reason="leaf node"),
            ScoredFileEntry(path="src/core.py", tier_index=1, confidence="high", confidence_reason="core component"),
            ScoredFileEntry(path="tests/test_core.py", tier_index=2, confidence="medium", confidence_reason="test file"),
        ],
        repo_confidence_summary=RepoConfidenceSummary(high_pct=66.7, medium_pct=33.3, low_pct=0.0),
        isolated_files=[],
        cyclic_files=[],
    )

    refined_res = RefinedOrderingResult(
        tiers=[
            RefinedTier(tier_index=0, ordered_files=[FileOrderEntry(path="src/utils.py", tie_break_method="none")]),
            RefinedTier(tier_index=1, ordered_files=[FileOrderEntry(path="src/core.py", tie_break_method="none")]),
            RefinedTier(tier_index=2, ordered_files=[FileOrderEntry(path="tests/test_core.py", tie_break_method="heuristic")]),
        ],
        isolated_files=[],
        cyclic_files=[],
        node_metadata={
            "src/utils.py": NodeMetadata(path="src/utils.py", domain="backend"),
            "src/core.py": NodeMetadata(path="src/core.py", domain="core"),
            "tests/test_core.py": NodeMetadata(path="tests/test_core.py", domain="tests"),
        },
    )

    narrator = NarrationEngine()
    narration_result = narrator.generate_narration(scored_seq, refined_res)

    # 4. Synthesize report
    synth = SynthesisEngine()
    report = synth.synthesize(
        repo_name="sample-app",
        segmentation_result=seg_res,
        narration_result=narration_result,
        parsed_files=[file1, file2, file3],
    )

    assert report.repo_name == "sample-app"
    assert report.architecture_overview.total_files == 3
    assert report.architecture_overview.primary_language == "python"
    assert "src/core.py" in report.architecture_overview.entry_point_files
    assert report.total_milestones >= 3
    assert report.milestones[0].tier == 0
    assert "helper_fn" in report.milestones[0].key_symbols_and_exports


def test_synthesis_engine_with_rag_citations():
    file1 = FileNode(path="src/math_util.py", language="python", exports=["add_two"])
    contents = {"src/math_util.py": "def add_two(a, b):\n    return a + b\n"}

    seg_res = SegmentationResult(
        files=[
            SegmentedFileNode(path="src/math_util.py", domain=DomainType.CORE, classification_method=ClassificationMethod.CONVENTION, confidence=ConfidenceLevel.HIGH),
        ],
        domain_counts={"core": 1},
        method_counts={"convention": 1},
    )

    scored_seq = ScoredOrderingResult(
        files=[
            ScoredFileEntry(path="src/math_util.py", tier_index=0, confidence="high", confidence_reason="leaf node"),
        ],
        repo_confidence_summary=RepoConfidenceSummary(high_pct=100.0, medium_pct=0.0, low_pct=0.0),
        isolated_files=[],
        cyclic_files=[],
    )

    refined_res = RefinedOrderingResult(
        tiers=[
            RefinedTier(tier_index=0, ordered_files=[FileOrderEntry(path="src/math_util.py", tie_break_method="none")]),
        ],
        isolated_files=[],
        cyclic_files=[],
        node_metadata={
            "src/math_util.py": NodeMetadata(path="src/math_util.py", domain="core"),
        },
    )

    narrator = NarrationEngine()
    narration_result = narrator.generate_narration(scored_seq, refined_res)

    rag = HybridRAGEngine(dimension=128)
    rag.index_repository([file1], contents)

    synth = SynthesisEngine()
    report = synth.synthesize(
        repo_name="math-lib",
        segmentation_result=seg_res,
        narration_result=narration_result,
        parsed_files=[file1],
        rag_engine=rag,
        file_contents=contents,
    )

    assert len(report.milestones) == 1
    assert len(report.milestones[0].deep_dive_citations) >= 1
    assert "src/math_util.py" in report.milestones[0].deep_dive_citations[0]


def test_synthesis_engine_reconciles_total_files_and_attaches_per_file_symbols():
    """
    Verify that total_files matches total segmentation files (including non-code files),
    per-file symbols are preserved, and file dependencies are extracted.
    """
    from app.parser.schema import ImportEdge

    # AST parsed code files (2 files)
    file_js = FileNode(
        path="src/App.jsx",
        language="javascript",
        exports=["App"],
        imports=[
            ImportEdge(target="src/Button.jsx", source_path="src/App.jsx", resolved=True, is_external=False)
        ],
    )
    file_btn = FileNode(path="src/Button.jsx", language="javascript", exports=["Button"])

    # 4 total repository files in segmentation (including CSS and config)
    seg_res = SegmentationResult(
        files=[
            SegmentedFileNode(path="src/App.jsx", domain=DomainType.FRONTEND, classification_method=ClassificationMethod.CONVENTION, confidence=ConfidenceLevel.HIGH),
            SegmentedFileNode(path="src/Button.jsx", domain=DomainType.FRONTEND, classification_method=ClassificationMethod.CONVENTION, confidence=ConfidenceLevel.HIGH),
            SegmentedFileNode(path="src/index.css", domain=DomainType.FRONTEND, classification_method=ClassificationMethod.CONVENTION, confidence=ConfidenceLevel.HIGH),
            SegmentedFileNode(path="package.json", domain=DomainType.CONFIG, classification_method=ClassificationMethod.CONVENTION, confidence=ConfidenceLevel.HIGH),
        ],
        domain_counts={"frontend": 3, "config": 1},
        method_counts={"convention": 4},
    )

    scored_seq = ScoredOrderingResult(
        files=[
            ScoredFileEntry(path="src/index.css", tier_index=0, confidence="high", confidence_reason="leaf"),
            ScoredFileEntry(path="src/Button.jsx", tier_index=0, confidence="high", confidence_reason="leaf"),
            ScoredFileEntry(path="src/App.jsx", tier_index=1, confidence="high", confidence_reason="dependent"),
            ScoredFileEntry(path="package.json", tier_index=0, confidence="high", confidence_reason="build"),
        ],
        repo_confidence_summary=RepoConfidenceSummary(high_pct=100.0, medium_pct=0.0, low_pct=0.0),
        isolated_files=[],
        cyclic_files=[],
    )

    refined_res = RefinedOrderingResult(
        tiers=[
            RefinedTier(tier_index=0, ordered_files=[
                FileOrderEntry(path="src/index.css", tie_break_method="none"),
                FileOrderEntry(path="src/Button.jsx", tie_break_method="none"),
                FileOrderEntry(path="package.json", tie_break_method="none"),
            ]),
            RefinedTier(tier_index=1, ordered_files=[
                FileOrderEntry(path="src/App.jsx", tie_break_method="none"),
            ]),
        ],
        isolated_files=[],
        cyclic_files=[],
        node_metadata={
            "src/index.css": NodeMetadata(path="src/index.css", domain="frontend"),
            "src/Button.jsx": NodeMetadata(path="src/Button.jsx", domain="frontend"),
            "package.json": NodeMetadata(path="package.json", domain="config"),
            "src/App.jsx": NodeMetadata(path="src/App.jsx", domain="frontend"),
        },
    )

    narrator = NarrationEngine()
    narration_result = narrator.generate_narration(scored_seq, refined_res)

    synth = SynthesisEngine()
    report = synth.synthesize(
        repo_name="react-app",
        segmentation_result=seg_res,
        narration_result=narration_result,
        parsed_files=[file_js, file_btn],
    )

    # 1. Total files reconciles with 4 total segmented repo files
    assert report.architecture_overview.total_files == 4
    assert sum(report.architecture_overview.domain_file_counts.values()) == 4

    # 2. Per-file symbols attached
    assert report.file_symbols.get("src/App.jsx") == ["App"]
    assert report.file_symbols.get("src/Button.jsx") == ["Button"]
    assert report.file_symbols.get("src/index.css") is None  # No JS symbols for CSS

    # 3. File dependencies extracted
    assert len(report.file_dependencies) == 1
    assert report.file_dependencies[0]["source"] == "src/App.jsx"
    assert report.file_dependencies[0]["target"] == "src/Button.jsx"

