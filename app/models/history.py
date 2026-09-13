"""Pydantic data models for Layer 3 Historical Signal Extraction."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class FileChange(BaseModel):
    """Represents a file change within a git commit."""
    path: str
    change_type: str  # 'added', 'modified', 'deleted', 'renamed'
    old_path: Optional[str] = None


class CommitSummary(BaseModel):
    """Structured summary of a git commit."""
    hash: str
    author: str
    timestamp: str
    message: str
    files_changed: List[FileChange] = Field(default_factory=list)


class FirstAppearance(BaseModel):
    """Represents the first creation/introduction of a file in git history."""
    commit_hash: str
    timestamp: str
    was_rename: bool = False
    original_path: Optional[str] = None


class CommitHistoryResult(BaseModel):
    """Complete historical signal extraction result."""
    history_available: bool = True
    commits: List[CommitSummary] = Field(default_factory=list)
    file_first_appearance: Dict[str, FirstAppearance] = Field(default_factory=dict)
    history_confidence: str = "high"  # "high" or "reduced"
    commit_count_processed: int = 0
    commit_count_total: int = 0
