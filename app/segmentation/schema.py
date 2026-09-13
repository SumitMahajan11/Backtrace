"""Pydantic data models and schemas for Layer 4 Code Base Segmentation Engine."""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class DomainType(str, Enum):
    """Categorization of repository files into architectural domains."""
    FRONTEND = "frontend"
    BACKEND = "backend"
    DATABASE = "database"
    DOCS = "docs"
    CONFIG = "config"
    TESTS = "tests"
    CORE = "core"
    UNCATEGORIZED = "uncategorized"


class ClassificationMethod(str, Enum):
    """Method used to classify a file into its domain."""
    CONVENTION = "convention"
    GRAPH = "graph"
    UNCATEGORIZED = "uncategorized"


class ConfidenceLevel(str, Enum):
    """Confidence rating of the domain classification."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SegmentedFileNode(BaseModel):
    """Represents a file with its assigned domain and classification metadata."""
    path: str
    domain: DomainType
    classification_method: ClassificationMethod
    confidence: ConfidenceLevel
    language: Optional[str] = None


class SegmentationResult(BaseModel):
    """Complete segmentation analysis result for a repository."""
    files: List[SegmentedFileNode] = Field(default_factory=list)
    domain_counts: Dict[str, int] = Field(default_factory=dict)
    method_counts: Dict[str, int] = Field(default_factory=dict)
