"""Layer 4 Code Base Segmentation Module."""

from app.segmentation.engine import SegmentationEngine
from app.segmentation.graph_clusterer import DependencyGraphClusterer
from app.segmentation.rules import ConventionRulesEngine
from app.segmentation.schema import (
    ClassificationMethod,
    ConfidenceLevel,
    DomainType,
    SegmentedFileNode,
    SegmentationResult,
)

__all__ = [
    "SegmentationEngine",
    "ConventionRulesEngine",
    "DependencyGraphClusterer",
    "DomainType",
    "ClassificationMethod",
    "ConfidenceLevel",
    "SegmentedFileNode",
    "SegmentationResult",
]
