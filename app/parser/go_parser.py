"""Go Static Structural Parser extending SubprocessLanguageParser (Layer 2 core)."""

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from app.parser.schema import FileNode, ImportCategory, ImportEdge, ParserResult
from app.parser.subprocess_base import SubprocessLanguageParser

GO_PARSER_DIR = Path(__file__).resolve().parent.parent.parent / "scripts" / "go_parser"
COMPILED_EXE = GO_PARSER_DIR / "go_parser.exe"
COMPILED_BIN = GO_PARSER_DIR / "go_parser"
MAIN_GO = GO_PARSER_DIR / "main.go"


class GoLanguageParser(SubprocessLanguageParser):
    """Go static structural parser using go/parser AST via Go subprocess helper."""

    @property
    def language_name(self) -> str:
        return "go"

    @property
    def file_extensions(self) -> Set[str]:
        return {".go"}

    @property
    def executable_cmd(self) -> List[str]:
        if COMPILED_EXE.exists():
            return [str(COMPILED_EXE)]
        if COMPILED_BIN.exists():
            return [str(COMPILED_BIN)]
        if shutil.which("go") and MAIN_GO.exists():
            return ["go", "run", str(MAIN_GO)]
        raise ValueError("Go parser executable not found and 'go' compiler unavailable")

    def parse_single_file(
        self, file_path: str, code_content: str, all_repo_files: Set[str]
    ) -> Tuple[FileNode, List[ImportEdge]]:
        data = self.execute_subprocess(file_path, code_content)

        pkg_name = data.get("package", "")
        classes: List[str] = data.get("classes", [])
        functions: List[str] = data.get("functions", [])
        exports: List[str] = data.get("exports", [])
        has_main: bool = data.get("has_main", False)

        is_entry = (pkg_name == "main" and has_main)
        entry_type = "main_function" if is_entry else None

        module_name = self._find_module_name(file_path, all_repo_files)

        edges: List[ImportEdge] = []
        for imp in data.get("imports", []):
            raw_path = imp.get("path", "")
            alias = imp.get("alias", "")
            is_blank = imp.get("is_blank", False)
            is_dot = imp.get("is_dot", False)
            line_no = imp.get("line_number")
            raw_str = imp.get("raw", raw_path)

            if is_blank:
                cat = ImportCategory.BLANK
            elif is_dot:
                cat = ImportCategory.WILDCARD
            else:
                cat = ImportCategory.STATIC

            target, is_ext, resolved = self._resolve_go_import(
                source_path=file_path,
                import_path=raw_path,
                module_name=module_name,
                all_repo_files=all_repo_files,
            )

            edges.append(
                ImportEdge(
                    target=target,
                    resolved=resolved,
                    import_type="blank" if is_blank else ("star" if is_dot else "static"),
                    source_path=file_path,
                    raw_import_symbol=raw_str,
                    category=cat,
                    is_external=is_ext,
                    line_number=line_no,
                )
            )

        file_node = FileNode(
            path=file_path,
            language=self.language_name,
            entry_point=is_entry,
            entry_point_type=entry_type,
            exports=exports,
            classes=classes,
            functions=functions,
            imports=edges,
        )

        return file_node, edges

    def parse_repository(
        self,
        file_paths: List[str],
        file_contents: Dict[str, str],
        timeout_per_file: float = 2.0,
    ) -> ParserResult:
        self._current_file_contents = file_contents
        try:
            return super().parse_repository(file_paths, file_contents, timeout_per_file)
        finally:
            self._current_file_contents = None

    def _find_module_name(self, source_path: str, all_repo_files: Set[str]) -> Optional[str]:
        """Finds go.mod module name if present."""
        go_mod_files = [f for f in all_repo_files if f.endswith("go.mod")]
        if not go_mod_files:
            return None

        file_contents = getattr(self, "_current_file_contents", None) or {}

        for mod_path in sorted(go_mod_files, key=len):
            content = file_contents.get(mod_path)
            if content is None and os.path.exists(mod_path):
                try:
                    with open(mod_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    content = None

            if content:
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("module "):
                        return line.split()[1]
        return None

    def set_module_name(self, module_name: str) -> None:
        """Explicitly set module name for testing."""
        self._override_module_name = module_name

    def _resolve_go_import(
        self,
        source_path: str,
        import_path: str,
        module_name: Optional[str],
        all_repo_files: Set[str],
    ) -> Tuple[str, bool, bool]:
        """
        Resolves a Go import path.
        Returns (target, is_external, resolved).
        """
        mod_name = getattr(self, "_override_module_name", None) or module_name

        first_segment = import_path.split("/")[0]
        is_stdlib = ("." not in first_segment)

        if is_stdlib:
            return import_path, False, True

        if mod_name and (import_path == mod_name or import_path.startswith(mod_name + "/")):
            rel_path = import_path[len(mod_name):].lstrip("/")
            has_matching_file = False
            for repo_file in all_repo_files:
                if rel_path == "":
                    if repo_file.endswith(".go") and "/" not in repo_file:
                        has_matching_file = True
                        break
                else:
                    if repo_file.startswith(rel_path + "/") and repo_file.endswith(".go"):
                        has_matching_file = True
                        break
                    if repo_file == rel_path or repo_file == f"{rel_path}.go":
                        has_matching_file = True
                        break

            target = rel_path if rel_path else mod_name
            return target, False, has_matching_file

        if import_path.startswith("."):
            source_dir = Path(source_path).parent
            resolved_base = (source_dir / import_path).as_posix()
            norm = os.path.normpath(resolved_base).replace("\\", "/")
            has_match = any(
                f.startswith(norm + "/") or f == norm or f == f"{norm}.go"
                for f in all_repo_files if f.endswith(".go")
            )
            return norm, False, has_match

        return import_path, True, False
