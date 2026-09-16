"""Layer 7: Synthesis / Manager Schema Definitions."""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from app.segmentation.schema import DomainType
from app.sequence.schema import BuildStepNarrative, SequenceNarrationResult


class SynthesizedMilestone(BaseModel):
    """Enriched milestone combining sequence reasoning with RAG code explanations and domain context."""
    tier: int
    title: str
    summary: str
    dominant_domain: str
    domain_breakdown: Dict[str, int] = Field(default_factory=dict)
    files: List[str] = Field(default_factory=list)
    confidence: str  # "high" | "medium" | "low"
    confidence_breakdown: Dict[str, int] = Field(default_factory=dict)
    is_cyclic: bool = False
    is_isolated: bool = False
    
    # Enriched contextual fields from Layer 5 RAG and Layer 4 Architecture
    architectural_role: str = ""
    key_symbols_and_exports: List[str] = Field(default_factory=list)
    deep_dive_citations: List[str] = Field(default_factory=list)
    prerequisite_tiers: List[int] = Field(default_factory=list)
    dependent_tiers: List[int] = Field(default_factory=list)
    pedagogical_hints: List[str] = Field(default_factory=list)
    implementation_gotchas: List[str] = Field(default_factory=list)


class ArchitectureOverview(BaseModel):
    """Overall structural and domain breakdown of the repository."""
    total_files: int
    total_domains: int
    domain_file_counts: Dict[str, int] = Field(default_factory=dict)
    primary_language: str
    entry_point_files: List[str] = Field(default_factory=list)
    cyclic_cluster_file_count: int = 0
    isolated_file_count: int = 0


class SynthesizedRepositoryReport(BaseModel):
    """Unified master output model produced by Layer 7 Synthesis Engine."""
    repo_name: str
    architecture_overview: ArchitectureOverview
    confidence_disclosure: str
    milestones: List[SynthesizedMilestone] = Field(default_factory=list)
    total_milestones: int
    synthesis_timestamp: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
