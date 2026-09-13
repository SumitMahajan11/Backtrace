"""Language-agnostic Output Schema (Intermediate Representation) for Layer 2."""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ImportCategory(str, Enum):
    """Categorization of imports across supported languages."""
    STATIC = "static"
    DYNAMIC = "dynamic"
    CONDITIONAL = "conditional"
    WILDCARD = "star"
    BLANK = "blank"


class ImportEdge(BaseModel):
    """Represents a dependency import edge between files or external packages."""
    target: str
    resolved: bool = True
    import_type: str = "static"  # "static" | "dynamic" | "conditional" | "star"
    source_path: str = ""
    raw_import_symbol: str = ""
    category: ImportCategory = ImportCategory.STATIC
    is_external: bool = False
    line_number: Optional[int] = None

    @property
    def target_path(self) -> str:
        return self.target


class FileNode(BaseModel):
    """Represents structural metadata extracted for a single source file."""
    path: str
    language: str
    entry_point: bool = False
    exports: List[str] = Field(default_factory=list)
    imports: List[ImportEdge] = Field(default_factory=list)
    entry_point_type: Optional[str] = None
    classes: List[str] = Field(default_factory=list)
    functions: List[str] = Field(default_factory=list)

    @property
    def is_entry_point(self) -> bool:
        return self.entry_point


# Aliases for schema compatibility
ParserFileNode = FileNode


class ParseError(BaseModel):
    """Represents a syntax/parse error captured without crashing the pipeline."""
    path: str
    language: str
    error_message: str


# Alias for backward compatibility
ParseErrorNode = ParseError


class ParserResult(BaseModel):
    """Complete output produced by a language parser for a repository."""
    language: str
    parser_version: str = "1.0.0"
    files: List[FileNode] = Field(default_factory=list)
    unresolved_imports: List[str] = Field(default_factory=list)
    parse_errors: List[ParseError] = Field(default_factory=list)
    external_dependencies: List[str] = Field(default_factory=list)

    @property
    def file_nodes(self) -> List[FileNode]:
        return self.files

    @property
    def import_edges(self) -> List[ImportEdge]:
        edges: List[ImportEdge] = []
        for file in self.files:
            edges.extend(file.imports)
        return edges
