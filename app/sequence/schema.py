"""Data models and schemas for Layer 6 Sequence Reasoning Engine (Stages A, B, & C)."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


# --- Stage A Schemas ---

class Tier(BaseModel):
    """Represents an ordered topological tier or a cyclic cluster group."""
    tier_index: int
    files: List[str] = Field(default_factory=list)
    is_cyclic_cluster: bool = False


class NodeMetadata(BaseModel):
    """Metadata associated with a file node in the dependency graph."""
    path: str
    domain: Optional[str] = "uncategorized"
    is_cyclic: bool = False
    dependencies_count: int = 0  # Number of internal resolved files this file depends on
    dependents_count: int = 0    # Number of internal resolved files depending on this file


class BaselineOrderingResult(BaseModel):
    """Output structure of Layer 6 (Stage A) Deterministic Baseline Ordering."""
    tiers: List[Tier] = Field(default_factory=list)
    isolated_files: List[str] = Field(default_factory=list)
    cyclic_files: List[str] = Field(default_factory=list)
    node_metadata: Dict[str, NodeMetadata] = Field(default_factory=dict)


# --- Stage B Schemas ---

class FileOrderEntry(BaseModel):
    """Represents an ordered file entry within a refined tier with tie-break metadata."""
    path: str
    tie_break_method: str  # "history" | "heuristic" | "llm" | "unresolved" | "none"
    reasoning: Optional[str] = None  # Reasoning explanation (populated for "llm" method)


class RefinedTier(BaseModel):
    """Represents a topological tier with intra-tier file ordering refined by Stage B."""
    tier_index: int
    ordered_files: List[FileOrderEntry] = Field(default_factory=list)
    is_cyclic_cluster: bool = False


class RefinedOrderingResult(BaseModel):
    """Output structure of Layer 6 (Stage B) Constrained Tie-Breaking."""
    tiers: List[RefinedTier] = Field(default_factory=list)
    isolated_files: List[str] = Field(default_factory=list)
    cyclic_files: List[str] = Field(default_factory=list)
    node_metadata: Dict[str, NodeMetadata] = Field(default_factory=dict)


# --- Stage C Schemas ---

class ScoredFileEntry(BaseModel):
    """Represents an ordered file entry with assigned confidence rating and explicit reason."""
    path: str
    tier_index: int  # -1 for isolated files
    confidence: str  # "high" | "medium" | "low"
    confidence_reason: str  # Human-readable specific rationale
    tie_break_method: Optional[str] = None
    reasoning: Optional[str] = None  # LLM reasoning if applicable


class RepoConfidenceSummary(BaseModel):
    """Overall confidence metrics summary across all files in the repository."""
    high_pct: float
    medium_pct: float
    low_pct: float
    history_available: bool = True


class ScoredOrderingResult(BaseModel):
    """Output structure of Layer 6 (Stage C) Confidence Scoring."""
    files: List[ScoredFileEntry] = Field(default_factory=list)
    repo_confidence_summary: RepoConfidenceSummary
    isolated_files: List[str] = Field(default_factory=list)
    cyclic_files: List[str] = Field(default_factory=list)


# --- Stage D Schemas ---

class BuildStepNarrative(BaseModel):
    """Represents an architectural build step narrative corresponding to a tier or milestone."""
    step_number: int
    title: str
    tier_index: int
    files: List[str] = Field(default_factory=list)
    domain_groups: Dict[str, List[str]] = Field(default_factory=dict)
    dominant_domain: str = "core"  # e.g. "tests", "core", "backend", "examples", "mixed"
    is_cyclic_cluster: bool = False
    dominant_confidence: str  # "high" | "medium" | "low"
    confidence_breakdown: Dict[str, int] = Field(default_factory=dict)  # e.g. {"high": 25, "medium": 5, "low": 8}
    pedagogical_explanation: str
    key_symbols_or_concepts: List[str] = Field(default_factory=list)




class SequenceNarrationResult(BaseModel):
    """Output structure of Layer 6 (Stage D) Sequence Narration."""
    overview: str
    confidence_disclosure: str
    steps: List[BuildStepNarrative] = Field(default_factory=list)
    isolated_files_summary: str
    prompt_used: Optional[str] = None

