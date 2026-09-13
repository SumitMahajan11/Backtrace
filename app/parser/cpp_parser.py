"""C++ Static Structural Parser using libclang Python bindings (Layer 2 core)."""

import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import clang.cindex

from app.parser.base import BaseLanguageParser
from app.parser.schema import FileNode, ImportCategory, ImportEdge


class CppLanguageParser(BaseLanguageParser):
    """
    C++ static structural parser using libclang Python bindings (clang.cindex).
    
    Parses both source files (.cpp, .cc, .cxx, .c) and header files (.h, .hpp, .hxx, .hh).
    
    Extracts:
    - Preprocessor `#include` directives (system vs local)
    - Top-level struct/class/union/template declarations
    - Top-level function/method declarations
    - Entry points (`int main(...)`)
    - Macro & template invocations recorded as informational import edges
    
    Diagnostic Classification:
    - Missing header diagnostics (e.g. "'foo.h' file not found") are NON-FATAL.
    - Genuine syntax errors in the file itself raise ValueError -> recorded as ParseError.
    """

    @property
    def language_name(self) -> str:
        return "cpp"

    @property
    def file_extensions(self) -> Set[str]:
        return {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hxx", ".hh"}

    def parse_single_file(
        self, file_path: str, code_content: str, all_repo_files: Set[str]
    ) -> Tuple[FileNode, List[ImportEdge]]:
        idx = clang.cindex.Index.create()

        args = ["-x", "c++", "-std=c++20"] if not file_path.endswith(".c") else ["-x", "c", "-std=c11"]
        options = clang.cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD

        try:
            tu = idx.parse(
                file_path,
                unsaved_files=[(file_path, code_content)],
                args=args,
                options=options,
            )
        except Exception as e:
            raise ValueError(f"libclang failed to parse '{file_path}': {e}") from e

        # Diagnostic classification: fatal syntax error vs non-fatal missing header
        fatal_syntax_errors = []
        for diag in tu.diagnostics:
            if diag.severity >= clang.cindex.Diagnostic.Error:
                msg = diag.spelling.lower()
                # Missing header error or cascading limit errors are non-fatal
                if "file not found" in msg or ("header" in msg and "not found" in msg) or "too many errors" in msg or "libfound" in msg or "module" in msg:
                    continue
                location_file = diag.location.file.name if diag.location and diag.location.file else ""
                if not location_file or location_file == file_path or file_path.endswith(location_file):
                    line_no = diag.location.line if diag.location else 0
                    fatal_syntax_errors.append(f"Line {line_no}: {diag.spelling}")

        if fatal_syntax_errors:
            raise ValueError(f"C++ syntax error in '{file_path}': {'; '.join(fatal_syntax_errors)}")

        classes: List[str] = []
        functions: List[str] = []
        exports: List[str] = []
        edges: List[ImportEdge] = []
        is_main = False

        # Extract preprocessor includes lexically
        lines = code_content.splitlines()
        include_pattern = r'^\s*#\s*include\s*([<"])([^>"]+)[>"]'

        for line_idx, line in enumerate(lines, start=1):
            line_strip = line.strip()
            match = re.search(include_pattern, line_strip)
            if match:
                delim = match.group(1)
                inc_target = match.group(2)

                is_system = (delim == "<") or self._is_stdlib_header(inc_target)

                if is_system:
                    edges.append(
                        ImportEdge(
                            target=inc_target,
                            resolved=True,
                            import_type="static",
                            source_path=file_path,
                            raw_import_symbol=f"#include <{inc_target}>",
                            category=ImportCategory.STATIC,
                            is_external=True,
                            line_number=line_idx,
                        )
                    )
                else:
                    target_resolved, is_resolved = self._resolve_local_include(
                        file_path, inc_target, all_repo_files
                    )
                    edges.append(
                        ImportEdge(
                            target=target_resolved,
                            resolved=is_resolved,
                            import_type="static",
                            source_path=file_path,
                            raw_import_symbol=f'#include "{inc_target}"',
                            category=ImportCategory.STATIC,
                            is_external=not is_resolved,
                            line_number=line_idx,
                        )
                    )

        # AST Cursor traversal for symbols, macros, and templates
        seen_macros: Set[str] = set()
        seen_templates: Set[str] = set()

        def traverse_cursor(cursor):
            nonlocal is_main
            for child in cursor.get_children():
                if child.location and child.location.file:
                    child_file = child.location.file.name
                    if child_file != file_path and not file_path.endswith(child_file):
                        continue

                kind = child.kind

                if kind in {
                    clang.cindex.CursorKind.CLASS_DECL,
                    clang.cindex.CursorKind.STRUCT_DECL,
                    clang.cindex.CursorKind.CLASS_TEMPLATE,
                    clang.cindex.CursorKind.UNION_DECL,
                }:
                    if child.spelling:
                        classes.append(child.spelling)
                        exports.append(child.spelling)

                elif kind in {
                    clang.cindex.CursorKind.FUNCTION_DECL,
                    clang.cindex.CursorKind.CXX_METHOD,
                    clang.cindex.CursorKind.FUNCTION_TEMPLATE,
                }:
                    if child.spelling:
                        functions.append(child.spelling)
                        exports.append(child.spelling)
                        if child.spelling == "main":
                            is_main = True

                elif kind == clang.cindex.CursorKind.NAMESPACE:
                    traverse_cursor(child)

                elif kind in {
                    clang.cindex.CursorKind.MACRO_INSTANTIATION,
                    clang.cindex.CursorKind.MACRO_DEFINITION,
                }:
                    if child.spelling and child.spelling not in seen_macros:
                        seen_macros.add(child.spelling)
                        line_no = child.location.line if child.location else None
                        edges.append(
                            ImportEdge(
                                target=f"macro::{child.spelling}",
                                resolved=False,
                                import_type="macro",
                                source_path=file_path,
                                raw_import_symbol=f"macro {child.spelling}",
                                category=ImportCategory.DYNAMIC,
                                is_external=False,
                                line_number=line_no,
                            )
                        )

                elif kind == clang.cindex.CursorKind.TEMPLATE_REF:
                    if child.spelling and child.spelling not in seen_templates:
                        seen_templates.add(child.spelling)
                        line_no = child.location.line if child.location else None
                        edges.append(
                            ImportEdge(
                                target=f"template::{child.spelling}",
                                resolved=False,
                                import_type="template",
                                source_path=file_path,
                                raw_import_symbol=f"template {child.spelling}",
                                category=ImportCategory.DYNAMIC,
                                is_external=False,
                                line_number=line_no,
                            )
                        )

        traverse_cursor(tu.cursor)

        file_node = FileNode(
            path=file_path,
            language=self.language_name,
            entry_point=is_main,
            entry_point_type="main_function" if is_main else None,
            exports=sorted(list(set(exports))),
            classes=sorted(list(set(classes))),
            functions=sorted(list(set(functions))),
            imports=edges,
        )

        return file_node, edges

    def _is_stdlib_header(self, header: str) -> bool:
        stdlib_headers = {
            "iostream", "vector", "string", "map", "set", "unordered_map", "unordered_set",
            "memory", "algorithm", "utility", "cmath", "cstdio", "cstdlib", "cstring",
            "fstream", "sstream", "thread", "mutex", "future", "chrono", "exception",
            "stdexcept", "cstdint", "cstddef", "type_traits", "functional", "tuple",
            "array", "deque", "list", "forward_list", "queue", "stack", "initializer_list",
            "stdio.h", "stdlib.h", "string.h", "math.h", "time.h", "assert.h",
        }
        return header.lower() in stdlib_headers

    def _resolve_local_include(
        self, source_path: str, inc_target: str, all_repo_files: Set[str]
    ) -> Tuple[str, bool]:
        source_dir = Path(source_path).parent
        candidate1 = (source_dir / inc_target).as_posix()
        norm1 = os.path.normpath(candidate1).replace("\\", "/")

        if norm1 in all_repo_files:
            return norm1, True
        if inc_target in all_repo_files:
            return inc_target, True

        for prefix in ["include", "src"]:
            candidate2 = f"{prefix}/{inc_target}"
            if candidate2 in all_repo_files:
                return candidate2, True

        return norm1, False
