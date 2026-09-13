"""Data models and schemas for Layer 5 Hybrid Vector + Graph RAG Engine."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class CodeChunk(BaseModel):
    """Represents a chunk of code content with symbol and line metadata."""
    chunk_id: str
    file_path: str
    start_line: int
    end_line: int
    content: str
    symbol_name: Optional[str] = None
    language: Optional[str] = None

    @property
    def line_range_str(self) -> str:
        symbol_info = f" ({self.symbol_name})" if self.symbol_name else ""
        return f"{self.file_path}:L{self.start_line}-L{self.end_line}{symbol_info}"


class CitationSource(BaseModel):
    """Citation metadata for tracing generated answers back to source lines."""
    file_path: str
    start_line: int
    end_line: int
    symbol_name: Optional[str] = None
    line_range_str: str


class RetrievedChunk(BaseModel):
    """A code chunk returned during hybrid retrieval, tagged with score and sources."""
    chunk: CodeChunk
    score: float = 0.0
    retrieval_sources: List[str] = Field(default_factory=list)  # ["vector"], ["graph"], or ["vector", "graph"]


class RAGQueryResult(BaseModel):
    """Complete response returned by the Hybrid RAG Engine."""
    query: str
    retrieved_chunks: List[RetrievedChunk] = Field(default_factory=list)
    formatted_context: str = ""
    citations: List[CitationSource] = Field(default_factory=list)
