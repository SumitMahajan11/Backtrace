"""Shell Script Static Structural Parser (Layer 2 core)."""

import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from app.parser.base import BaseLanguageParser
from app.parser.schema import FileNode, ImportCategory, ImportEdge, ParseError, ParserResult
from app.security.regex_safety import safe_regex_search


class ShellLanguageParser(BaseLanguageParser):
    """
    Lightweight, in-process static structural parser for Shell scripts (.sh, .bash, .zsh, or shebang files).
    
    Extracts:
    - Sourced scripts: `source <path>` or `. <path>`
    - Executable invocations: `./<path>`, `bash <path>`, `sh <path>`, `zsh <path>`
    - Dynamic variable-constructed paths: e.g. `source "$SCRIPT_DIR/env.sh"` -> import_type="dynamic"
    - Entry points: scripts containing a shell shebang (`#!/bin/...`)
    """

    @property
    def language_name(self) -> str:
        return "shell"

    @property
    def file_extensions(self) -> Set[str]:
        return {".sh", ".bash", ".zsh", ".ksh"}

    def parse_repository(
        self,
        file_paths: List[str],
        file_contents: Dict[str, str],
        timeout_per_file: float = 2.0,
    ) -> ParserResult:
        """Overridden to include non-.sh files that contain a shell shebang header."""
        all_repo_files = set(file_paths)
        file_nodes: List[FileNode] = []
        parse_errors: List[ParseError] = []
        external_deps: Set[str] = set()
        unresolved_imports: Set[str] = set()

        matching_files = []
        for path in file_paths:
            ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if ext in self.file_extensions:
                matching_files.append(path)
            else:
                content = file_contents.get(path, "")
                if content and self._has_shell_shebang(content):
                    matching_files.append(path)

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

    def _has_shell_shebang(self, content: str) -> bool:
        first_line = content.lstrip().splitlines()[0] if content.lstrip() else ""
        if first_line.startswith("#!"):
            line_lower = first_line.lower()
            return any(sh in line_lower for sh in ["bash", "sh", "zsh", "ksh", "ash", "dash"])
        return False

    def parse_single_file(
        self, file_path: str, code_content: str, all_repo_files: Set[str]
    ) -> Tuple[FileNode, List[ImportEdge]]:
        # Sanity check for binary garbage
        if "\x00" in code_content:
            raise ValueError("Binary content detected in shell file")

        is_entry = self._has_shell_shebang(code_content)
        entry_type = "shell_script" if is_entry else None

        edges: List[ImportEdge] = []
        lines = code_content.splitlines()

        # Regex patterns for line-by-line matching
        source_pattern = r'^\s*(?:source|\.)\s+([^\s;#]+)'
        exec_pattern = r'^\s*(?:(?:bash|sh|zsh|ksh)\s+|\./)([^\s;#]+\.sh|[^\s;#]+\.bash|[^\s;#]+)'

        for idx, line in enumerate(lines, start=1):
            line_strip = line.strip()
            if not line_strip or line_strip.startswith("#"):
                continue

            # ReDoS safety check via safe_regex_search for long lines (> 200 chars)
            if len(line_strip) > 200:
                safe_regex_search(source_pattern, line_strip, timeout_seconds=0.5)

            # 1. Source / Dot command matching
            source_match = re.search(source_pattern, line_strip)
            if source_match:
                raw_target = source_match.group(1).strip('"\'')
                edge = self._build_import_edge(
                    file_path, raw_target, "source", idx, all_repo_files
                )
                edges.append(edge)
                continue

            # 2. Direct script invocation matching
            exec_match = re.search(exec_pattern, line_strip)
            if exec_match:
                raw_target = exec_match.group(1).strip('"\'')
                if not raw_target.startswith("-") and ("/" in raw_target or raw_target.endswith(".sh") or raw_target.endswith(".bash")):
                    edge = self._build_import_edge(
                        file_path, raw_target, "invocation", idx, all_repo_files
                    )
                    edges.append(edge)

        file_node = FileNode(
            path=file_path,
            language=self.language_name,
            entry_point=is_entry,
            entry_point_type=entry_type,
            exports=[],
            classes=[],
            functions=[],
            imports=edges,
        )

        return file_node, edges

    def _build_import_edge(
        self,
        source_path: str,
        raw_target: str,
        import_kind: str,
        line_number: int,
        all_repo_files: Set[str],
    ) -> ImportEdge:
        is_dynamic = bool(re.search(r'\$[A-Za-z0-9_]+|\$\{[^}]+\}', raw_target))

        if is_dynamic:
            return ImportEdge(
                target=raw_target,
                resolved=False,
                import_type="dynamic",
                source_path=source_path,
                raw_import_symbol=raw_target,
                category=ImportCategory.DYNAMIC,
                is_external=False,
                line_number=line_number,
            )

        source_dir = Path(source_path).parent
        resolved_base = (source_dir / raw_target).as_posix()
        norm_path = os.path.normpath(resolved_base).replace("\\", "/")

        has_match = False
        target_final = norm_path

        if norm_path in all_repo_files:
            has_match = True
        elif raw_target in all_repo_files:
            has_match = True
            target_final = raw_target

        cat = ImportCategory.STATIC

        return ImportEdge(
            target=target_final,
            resolved=has_match,
            import_type=import_kind,
            source_path=source_path,
            raw_import_symbol=raw_target,
            category=cat,
            is_external=not has_match and not raw_target.startswith("."),
            line_number=line_number,
        )
