"""Unit tests for Layer 4 DependencyGraphClusterer and graph fallback."""

import pytest
from app.parser.schema import FileNode, ImportEdge
from app.segmentation.engine import SegmentationEngine
from app.segmentation.graph_clusterer import DependencyGraphClusterer
from app.segmentation.schema import ClassificationMethod, ConfidenceLevel, DomainType


def test_graph_fallback_clustering():
    # 1. Construct synthetic repo where an ambiguous file has import ties to backend files
    # Convention will categorize backend_api.py and backend_server.py as BACKEND
    # helper.xyz is uncategorized by convention
    file_nodes = [
        FileNode(
            path="server/backend_api.py",
            language="python",
            imports=[
                ImportEdge(target="server/backend_server.py", resolved=True, is_external=False),
                ImportEdge(target="shared/helper.xyz", resolved=True, is_external=False),
            ],
        ),
        FileNode(
            path="server/backend_server.py",
            language="python",
            imports=[
                ImportEdge(target="shared/helper.xyz", resolved=True, is_external=False),
            ],
        ),
        FileNode(
            path="shared/helper.xyz",
            language="unknown",
            imports=[
                ImportEdge(target="server/backend_api.py", resolved=True, is_external=False),
            ],
        ),
    ]

    engine = SegmentationEngine()
    result = engine.segment_repository(file_nodes)

    result_map = {f.path: f for f in result.files}

    # Convention matches
    assert result_map["server/backend_api.py"].domain == DomainType.BACKEND
    assert result_map["server/backend_api.py"].classification_method == ClassificationMethod.CONVENTION
    assert result_map["server/backend_api.py"].confidence == ConfidenceLevel.HIGH

    assert result_map["server/backend_server.py"].domain == DomainType.BACKEND
    assert result_map["server/backend_server.py"].classification_method == ClassificationMethod.CONVENTION

    # Graph fallback match for ambiguous file
    assert result_map["shared/helper.xyz"].domain == DomainType.BACKEND
    assert result_map["shared/helper.xyz"].classification_method == ClassificationMethod.GRAPH
    assert result_map["shared/helper.xyz"].confidence == ConfidenceLevel.MEDIUM


def test_graph_fallback_isolated_ambiguous_file():
    # An isolated ambiguous file with no imports remains UNCATEGORIZED
    file_nodes = [
        FileNode(
            path="custom/standalone.unknown",
            language="unknown",
            imports=[],
        )
    ]

    engine = SegmentationEngine()
    result = engine.segment_repository(file_nodes)

    node = result.files[0]
    assert node.domain == DomainType.UNCATEGORIZED
    assert node.classification_method == ClassificationMethod.UNCATEGORIZED
    assert node.confidence == ConfidenceLevel.LOW


def test_graph_fallback_core_clustering():
    # Ambiguous file clustering with CORE files should be classified as CORE
    file_nodes = [
        FileNode(
            path="src/lib.rs",
            language="rust",
            imports=[
                ImportEdge(target="src/internal_helper.custom", resolved=True, is_external=False),
            ],
        ),
        FileNode(
            path="src/runtime.rs",
            language="rust",
            imports=[
                ImportEdge(target="src/internal_helper.custom", resolved=True, is_external=False),
            ],
        ),
        FileNode(
            path="src/internal_helper.custom",
            language="unknown",
            imports=[
                ImportEdge(target="src/lib.rs", resolved=True, is_external=False),
            ],
        ),
    ]

    engine = SegmentationEngine()
    result = engine.segment_repository(file_nodes)

    result_map = {f.path: f for f in result.files}
    assert result_map["src/internal_helper.custom"].domain == DomainType.CORE
    assert result_map["src/internal_helper.custom"].classification_method == ClassificationMethod.GRAPH
    assert result_map["src/internal_helper.custom"].confidence == ConfidenceLevel.MEDIUM

