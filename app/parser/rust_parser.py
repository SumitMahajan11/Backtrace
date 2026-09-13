"""Rust Static Structural Parser extending SubprocessLanguageParser (Layer 2 core)."""

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from app.parser.schema import FileNode, ImportCategory, ImportEdge, ParserResult
from app.parser.subprocess_base import SubprocessLanguageParser

RUST_PARSER_DIR = Path(__file__).resolve().parent.parent.parent / "scripts" / "rust_parser"
RELEASE_EXE = RUST_PARSER_DIR / "target" / "release" / "rust_parser.exe"
RELEASE_BIN = RUST_PARSER_DIR / "target" / "release" / "rust_parser"
DEBUG_EXE = RUST_PARSER_DIR / "target" / "debug" / "rust_parser.exe"
DEBUG_BIN = RUST_PARSER_DIR / "target" / "debug" / "rust_parser"
CARGO_TOML = RUST_PARSER_DIR / "Cargo.toml"


class RustLanguageParser(SubprocessLanguageParser):
    """Rust static structural parser using syn AST via Rust subprocess helper."""

    @property
    def language_name(self) -> str:
        return "rust"

    @property
    def file_extensions(self) -> Set[str]:
        return {".rs"}

    @property
    def executable_cmd(self) -> List[str]:
        if RELEASE_EXE.exists():
            return [str(RELEASE_EXE)]
        if RELEASE_BIN.exists():
            return [str(RELEASE_BIN)]
        if DEBUG_EXE.exists():
            return [str(DEBUG_EXE)]
        if DEBUG_BIN.exists():
            return [str(DEBUG_BIN)]
        if shutil.which("cargo") and CARGO_TOML.exists():
            return ["cargo", "run", "--quiet", "--manifest-path", str(CARGO_TOML)]
        raise ValueError("Rust parser executable not found and 'cargo' toolchain unavailable")

    def parse_single_file(
        self, file_path: str, code_content: str, all_repo_files: Set[str]
    ) -> Tuple[FileNode, List[ImportEdge]]:
        data = self.execute_subprocess(file_path, code_content)

        classes: List[str] = data.get("classes", [])
        functions: List[str] = data.get("functions", [])
        exports: List[str] = data.get("exports", [])
        has_main: bool = data.get("has_main", False)
        unresolved_macros: List[str] = data.get("unresolved_macros", [])

        file_name = Path(file_path).name.lower()
        is_entry = (has_main and file_name in {"main.rs", "lib.rs"}) or (file_name == "main.rs")
        entry_type = "main_function" if is_entry else None

        crate_name = self._find_crate_name(file_path, all_repo_files)

        edges: List[ImportEdge] = []

        # Process 'use' imports
        for imp in data.get("imports", []):
            raw_path = imp.get("path", "")
            alias = imp.get("alias", "")
            is_wildcard = imp.get("is_wildcard", False)
            line_no = imp.get("line_number")
            raw_str = imp.get("raw", raw_path)

            if is_wildcard:
                cat = ImportCategory.WILDCARD
                imp_type = "star"
            else:
                cat = ImportCategory.STATIC
                imp_type = "static"

            target, is_ext, resolved = self._resolve_rust_use_import(
                source_path=file_path,
                import_path=raw_path,
                crate_name=crate_name,
                all_repo_files=all_repo_files,
            )

            edges.append(
                ImportEdge(
                    target=target,
                    resolved=resolved,
                    import_type=imp_type,
                    source_path=file_path,
                    raw_import_symbol=raw_str,
                    category=cat,
                    is_external=is_ext,
                    line_number=line_no,
                )
            )

        # Process 'mod' declarations (e.g. mod foo;)
        for mod in data.get("modules", []):
            mod_name = mod.get("name", "")
            is_inline = mod.get("is_inline", False)
            line_no = mod.get("line_number")

            if not is_inline and mod_name:
                target, resolved = self._resolve_rust_mod_declaration(
                    source_path=file_path,
                    mod_name=mod_name,
                    all_repo_files=all_repo_files,
                )
                edges.append(
                    ImportEdge(
                        target=target,
                        resolved=resolved,
                        import_type="static",
                        source_path=file_path,
                        raw_import_symbol=f"mod {mod_name};",
                        category=ImportCategory.STATIC,
                        is_external=False,
                        line_number=line_no,
                    )
                )

        # Record macro invocations as unresolved/uncertain import edges
        for macro_name in unresolved_macros:
            edges.append(
                ImportEdge(
                    target=f"macro::{macro_name}",
                    resolved=False,
                    import_type="macro",
                    source_path=file_path,
                    raw_import_symbol=f"macro! {macro_name}",
                    category=ImportCategory.DYNAMIC,
                    is_external=False,
                    line_number=None,
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

    def _find_crate_name(self, source_path: str, all_repo_files: Set[str]) -> Optional[str]:
        """Finds package name from Cargo.toml if present."""
        cargo_files = [f for f in all_repo_files if f.endswith("Cargo.toml")]
        if not cargo_files:
            return None

        file_contents = getattr(self, "_current_file_contents", None) or {}

        for mod_path in sorted(cargo_files, key=len):
            content = file_contents.get(mod_path)
            if content is None and os.path.exists(mod_path):
                try:
                    with open(mod_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    content = None

            if content:
                in_package = False
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("[package]"):
                        in_package = True
                        continue
                    if line.startswith("[") and line != "[package]":
                        in_package = False
                    if in_package and line.startswith("name ="):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            return parts[1].strip().strip('"').strip("'")
        return None

    def set_crate_name(self, crate_name: str) -> None:
        """Explicitly set crate name for testing."""
        self._override_crate_name = crate_name

    def _resolve_rust_use_import(
        self,
        source_path: str,
        import_path: str,
        crate_name: Optional[str],
        all_repo_files: Set[str],
    ) -> Tuple[str, bool, bool]:
        """
        Resolves a Rust 'use' import path.
        Returns (target, is_external, resolved).
        """
        c_name = getattr(self, "_override_crate_name", None) or crate_name

        first_segment = import_path.split("::")[0]
        is_stdlib = first_segment in {"std", "core", "alloc"}

        if is_stdlib:
            return import_path, False, True

        if first_segment in {"crate", "super", "self"}:
            rel_segments = import_path.split("::")[1:]
            rel_path = "/".join(rel_segments)
            has_match = self._find_matching_rs_file(rel_path, source_path, all_repo_files)
            target = rel_path if rel_path else import_path
            return target, False, has_match

        if c_name and (import_path == c_name or import_path.startswith(c_name + "::")):
            rel_segments = import_path.split("::")[1:]
            rel_path = "/".join(rel_segments)
            has_match = self._find_matching_rs_file(rel_path, source_path, all_repo_files)
            target = rel_path if rel_path else c_name
            return target, False, has_match

        return import_path, True, False

    def _resolve_rust_mod_declaration(
        self,
        source_path: str,
        mod_name: str,
        all_repo_files: Set[str],
    ) -> Tuple[str, bool]:
        """
        Resolves 'mod foo;' to foo.rs or foo/mod.rs.
        Returns (target_path, resolved).
        """
        source_dir = Path(source_path).parent.as_posix()
        if source_dir == ".":
            candidate1 = f"{mod_name}.rs"
            candidate2 = f"{mod_name}/mod.rs"
        else:
            candidate1 = f"{source_dir}/{mod_name}.rs"
            candidate2 = f"{source_dir}/{mod_name}/mod.rs"

        if candidate1 in all_repo_files:
            return candidate1, True
        if candidate2 in all_repo_files:
            return candidate2, True

        return candidate1, False

    def _find_matching_rs_file(
        self, rel_path: str, source_path: str, all_repo_files: Set[str]
    ) -> bool:
        if not rel_path:
            return True
        candidates = [
            f"{rel_path}.rs",
            f"{rel_path}/mod.rs",
            f"src/{rel_path}.rs",
            f"src/{rel_path}/mod.rs",
        ]
        return any(c in all_repo_files for c in candidates)
