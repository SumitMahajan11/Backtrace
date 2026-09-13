"""Abstract Base Class for per-language static structural parsers."""

import concurrent.futures
from abc import ABC, abstractmethod
from typing import Dict, List, Set, Tuple

from app.parser.schema import (
    FileNode,
    ImportEdge,
    ParseError,
    ParserResult,
)


class BaseLanguageParser(ABC):
    """Abstract base class for language-specific static structural parsers."""

    @property
    @abstractmethod
    def language_name(self) -> str:
        """Name of the programming language (e.g. 'python', 'javascript')."""
        pass

    @property
    @abstractmethod
    def file_extensions(self) -> Set[str]:
        """Supported file extensions (e.g. {'.py', '.pyw'})."""
        pass

    @abstractmethod
    def parse_single_file(
        self, file_path: str, code_content: str, all_repo_files: Set[str]
    ) -> Tuple[FileNode, List[ImportEdge]]:
        """Parses a single file's content and extracts node and import edges."""
        pass

    def parse_file_with_timeout(
        self, file_path: str, code_content: str, all_repo_files: Set[str], timeout_seconds: float = 2.0
    ) -> Tuple[FileNode, List[ImportEdge]]:
        """Wraps single-file parsing in a ThreadPoolExecutor timeout guard."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.parse_single_file, file_path, code_content, all_repo_files)
            try:
                return future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError as e:
                raise TimeoutError(
                    f"File '{file_path}' parsing timed out after {timeout_seconds}s."
                ) from e

    def parse_repository(
        self,
        file_paths: List[str],
        file_contents: Dict[str, str],
        timeout_per_file: float = 10.0,
    ) -> ParserResult:
        """Parses all matching files in repository and aggregates results."""
        normalized_paths = [p.path if hasattr(p, "path") else str(p) for p in file_paths]
        all_repo_files = set(normalized_paths)
        file_nodes: List[FileNode] = []
        parse_errors: List[ParseError] = []
        external_deps: Set[str] = set()
        unresolved_imports: Set[str] = set()

        matching_files = [
            p for p in normalized_paths if any(p.lower().endswith(ext) for ext in self.file_extensions)
        ]

        for path in matching_files:
            content = file_contents.get(path, "")
            try:
                node, edges = self.parse_file_with_timeout(
                    path, content, all_repo_files, timeout_seconds=timeout_per_file
                )
                node.imports = edges
                file_nodes.append(node)
                for edge in edges:
                    if edge.is_external:
                        external_deps.add(edge.target)
                    if not edge.resolved:
                        unresolved_imports.add(edge.target)
            except Exception as e:
                parse_errors.append(
                    ParseError(
                        path=path,
                        language=self.language_name,
                        error_message=str(e),
                    )
                )

        return ParserResult(
            language=self.language_name,
            parser_version="1.0.0",
            files=file_nodes,
            unresolved_imports=sorted(list(unresolved_imports)),
            parse_errors=parse_errors,
            external_dependencies=sorted(list(external_deps)),
        )
