"""JavaScript and TypeScript Static Structural Parser using @babel/parser AST (Layer 2 core)."""

import os
from pathlib import Path
from typing import Dict, List, Set, Tuple

from app.parser.subprocess_base import SubprocessLanguageParser
from app.parser.schema import FileNode, ImportCategory, ImportEdge

SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "parse_js.js"


class JavaScriptLanguageParser(SubprocessLanguageParser):
    """JavaScript and TypeScript static structural parser using @babel/parser AST via Node subprocess."""

    @property
    def language_name(self) -> str:
        return "javascript"

    @property
    def file_extensions(self) -> Set[str]:
        return {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

    @property
    def executable_cmd(self) -> List[str]:
        return ["node", str(SCRIPT_PATH)]

    def parse_single_file(
        self, file_path: str, code_content: str, all_repo_files: Set[str]
    ) -> Tuple[FileNode, List[ImportEdge]]:
        data = self.execute_subprocess(file_path, code_content)


        classes: List[str] = data.get("classes", [])
        functions: List[str] = data.get("functions", [])
        exports: List[str] = data.get("exports", [])
        edges: List[ImportEdge] = []

        path_obj = Path(file_path)
        filename = path_obj.name.lower()
        is_entry = filename in {"index.js", "index.ts", "app.js", "app.ts", "server.js", "server.ts", "main.js", "main.ts"}
        entry_type = "main_script" if is_entry else None

        category_map = {
            "static": ImportCategory.STATIC,
            "dynamic": ImportCategory.DYNAMIC,
            "wildcard": ImportCategory.WILDCARD,
        }

        for imp in data.get("imports", []):
            specifier = imp.get("specifier", "")
            imp_type = imp.get("import_type", "static")
            raw_cat = imp.get("category", "static")
            cat = category_map.get(raw_cat, ImportCategory.STATIC)
            line_no = imp.get("line_number")

            target, is_ext = self._resolve_js_import(file_path, specifier, all_repo_files)
            edges.append(
                ImportEdge(
                    target=target,
                    resolved=(imp_type != "dynamic" and not is_ext and target in all_repo_files),
                    import_type=imp_type,
                    source_path=file_path,
                    raw_import_symbol=imp.get("raw", specifier),
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

    def _resolve_js_import(
        self, source_path: str, specifier: str, all_repo_files: Set[str]
    ) -> Tuple[str, bool]:
        if not specifier.startswith("."):
            pkg_name = specifier.split("/")[0] if not specifier.startswith("@") else "/".join(specifier.split("/")[:2])
            return pkg_name, True

        source_dir = Path(source_path).parent
        resolved_base = (source_dir / specifier).as_posix()
        normalized_path = os.path.normpath(resolved_base).replace("\\", "/")

        candidates = [
            normalized_path,
            f"{normalized_path}.ts",
            f"{normalized_path}.tsx",
            f"{normalized_path}.js",
            f"{normalized_path}.jsx",
            f"{normalized_path}/index.ts",
            f"{normalized_path}/index.tsx",
            f"{normalized_path}/index.js",
        ]

        for cand in candidates:
            if cand in all_repo_files:
                return cand, False

        return normalized_path, False

