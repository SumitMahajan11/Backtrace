"""Layer 11: Pipeline Orchestration & Job Queue Schema."""

from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from pydantic import BaseModel, Field

from app.synthesis.schema import SynthesizedRepositoryReport


class PipelineStage(str, Enum):
    """Execution stages across the 11-layer architecture."""
    INGESTION = "ingestion"              # Layer 1 & Layer 10
    PARSING = "parsing"                  # Layer 2 & Layer 3
    UNDERSTANDING = "understanding"      # Layer 4 (Segmentation) & Layer 5 (RAG)
    SEQUENCE_REASONING = "reasoning"     # Layer 6 (Stages A, B, C, D)
    SYNTHESIS = "synthesis"              # Layer 7 & Layer 8
    COMPLETE = "complete"
    FAILED = "failed"


class PipelineProgressEvent(BaseModel):
    """Real-time progress update event emitted during pipeline execution."""
    stage: PipelineStage
    progress_pct: float
    message: str
    stage_details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str


class PipelineResult(BaseModel):
    """End-to-end execution result object."""
    success: bool
    repo_name: str
    report: Optional[SynthesizedRepositoryReport] = None
    markdown_output: str = ""
    graph_output: Dict[str, Any] = Field(default_factory=dict)
    quiz_output: Dict[str, Any] = Field(default_factory=dict)
    events: List[PipelineProgressEvent] = Field(default_factory=list)
    parse_errors: List[Dict[str, Any]] = Field(default_factory=list)
    uncategorized_files: List[str] = Field(default_factory=list)
    run_id: str = ""
    error: Optional[str] = None
    execution_time_seconds: float = 0.0

