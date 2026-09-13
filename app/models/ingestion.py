"""Pydantic data models and custom exceptions for Layer 1 Ingestion Service."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class FileNode(BaseModel):
    """Represents a file in the ingested repository tree."""
    path: str
    size_bytes: int
    extension: str
    file_type: str = "file"


class SkippedItem(BaseModel):
    """Represents a skipped file or directory with justification."""
    path: str
    reason: str


class RepoMetadata(BaseModel):
    """Metadata extracted during ingestion."""
    default_branch: str
    head_commit: str
    clone_duration_seconds: float
    submodule_urls: List[str] = Field(default_factory=list)


class IngestionResult(BaseModel):
    """Complete result returned by IngestionService."""
    file_tree: List[FileNode]
    file_contents: Dict[str, str]
    skipped_items: List[SkippedItem]
    metadata: RepoMetadata


class IngestionError(Exception):
    """Base exception for Ingestion errors."""
    pass


class InvalidURLError(IngestionError):
    """Raised when the provided GitHub URL is invalid or malformed."""
    pass


class SSRFError(IngestionError):
    """Raised when URL points to blocked IP address or SSRF target."""
    pass


class IngestionLimitExceededError(IngestionError):
    """Raised when repository exceeds file count or size constraints."""
    pass


class CloneTimeoutError(IngestionError):
    """Raised when git clone process exceeds allowed timeout."""
    pass
