"""Reference Python AST Structural Parser (Layer 2 core)."""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from app.parser.base import BaseLanguageParser
from app.parser.schema import FileNode, ImportCategory, ImportEdge

STD_LIB_PYTHON = {
    "os", "sys", "time", "datetime", "math", "re", "json", "ast", "pathlib", "typing",
    "socket", "subprocess", "shutil", "tempfile", "contextlib", "configparser", "enum",
    "ipaddress", "urllib", "concurrent", "unittest", "logging", "asyncio", "hashlib",
}


class PythonLanguageParser(BaseLanguageParser):
    """Python static AST structural parser."""

    @property
    def language_name(self) -> str:
        return "python"

    @property
    def file_extensions(self) -> Set[str]:
        return {".py", ".pyw"}

    def parse_single_file(
        self, file_path: str, code_content: str, all_repo_files: Set[str]
    ) -> Tuple[FileNode, List[ImportEdge]]:
        tree = ast.parse(code_content, filename=file_path)

        classes: List[str] = []
        functions: List[str] = []
        exports: List[str] = []
        is_entry, entry_type = self._detect_entry_point(file_path, code_content, tree)

        # Inspect top-level symbols for exports
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
                exports.append(node.name)
            elif isinstance(node, ast.FunctionDef):
                functions.append(node.name)
                exports.append(node.name)

        # Walk AST for imports
        visitor = PythonImportVisitor(file_path, all_repo_files)
        visitor.visit(tree)

        # Deduplicate edges by (source_file, target_file) pair
        deduped_edges: List[ImportEdge] = []
        seen_pairs: Set[Tuple[str, str]] = set()
        for e in visitor.edges:
            pair = (e.source_path or file_path, e.target)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                deduped_edges.append(e)
        edges = deduped_edges

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

    def _is_test_file(self, file_path: str) -> bool:
        """Checks if a file path matches tests/, test_*.py, *_test.py, or conftest.py."""
        norm = file_path.replace("\\", "/").strip("/")
        parts = norm.split("/")
        filename = parts[-1]
        if "tests" in parts or parts[0] == "tests" or "/tests/" in f"/{norm}/":
            return True
        if filename.startswith("test_") and filename.endswith(".py"):
            return True
        if filename.endswith("_test.py"):
            return True
        if filename == "conftest.py":
            return True
        return False

    def _detect_entry_point(
        self, file_path: str, code_content: str, tree: ast.AST
    ) -> Tuple[bool, Optional[str]]:
        """Determines if a file is an application entry point.

        Rules:
        1. Exclude any file whose path matches tests/, test_*.py, *_test.py, conftest.py.
        2. A file is an application entry point if ANY of:
           - it contains FastAPI( or Flask( or Django settings with WSGI/ASGI application
           - it contains if __name__ == "__main__"
           - it is named main.py, app.py, manage.py, wsgi.py, asgi.py, or server.py at repo root or inside top-level package
           - it contains uvicorn.run(
        """
        if self._is_test_file(file_path):
            return False, None

        # Rule 1: Framework application definitions
        if "FastAPI(" in code_content:
            return True, "fastapi_app"
        if "Flask(" in code_content:
            return True, "flask_app"
        if (
            "WSGI_APPLICATION" in code_content
            or "ASGI_APPLICATION" in code_content
            or "get_wsgi_application" in code_content
            or "get_asgi_application" in code_content
            or ("django" in code_content.lower() and ("wsgi" in code_content.lower() or "asgi" in code_content.lower()))
        ):
            return True, "django_app"

        # Rule 2: if __name__ == "__main__"
        if 'if __name__ == "__main__"' in code_content or "if __name__ == '__main__'" in code_content:
            return True, "name_eq_main"
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and self._is_name_main_check(node):
                return True, "name_eq_main"

        # Rule 3: Standard entry filenames at root or inside top-level package
        norm_path = file_path.replace("\\", "/").strip("/")
        parts = norm_path.split("/")
        filename = parts[-1]
        ENTRY_NAMES = {
            "main.py",
            "app.py",
            "manage.py",
            "wsgi.py",
            "asgi.py",
            "server.py",
            "__main__.py",
        }
        if len(parts) <= 2 and filename in ENTRY_NAMES:
            return True, "entry_filename"

        # Rule 4: contains uvicorn.run(
        if "uvicorn.run(" in code_content:
            return True, "uvicorn_run"

        return False, None

    def _is_name_main_check(self, node: ast.If) -> bool:
        if isinstance(node.test, ast.Compare):
            left = node.test.left
            if isinstance(left, ast.Name) and left.id == "__name__":
                for comparator in node.test.comparators:
                    if isinstance(comparator, ast.Constant) and comparator.value == "__main__":
                        return True
        return False


class PythonImportVisitor(ast.NodeVisitor):
    """AST visitor traversing imports and detecting conditional/dynamic contexts."""

    def __init__(self, source_path: str, all_repo_files: Set[str]):
        self.source_path = source_path
        self.all_repo_files = all_repo_files
        self.edges: List[ImportEdge] = []
        self.in_conditional = False

    def visit_If(self, node: ast.If):
        prev_conditional = self.in_conditional
        self.in_conditional = True
        self.generic_visit(node)
        self.in_conditional = prev_conditional

    def visit_Try(self, node: ast.Try):
        prev_conditional = self.in_conditional
        self.in_conditional = True
        self.generic_visit(node)
        self.in_conditional = prev_conditional

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            symbol = alias.name
            target, is_ext = self._resolve_python_import(symbol)
            cat = ImportCategory.CONDITIONAL if self.in_conditional else ImportCategory.STATIC
            imp_type = "conditional" if self.in_conditional else "static"
            self.edges.append(
                ImportEdge(
                    target=target,
                    resolved=not is_ext,
                    import_type=imp_type,
                    source_path=self.source_path,
                    raw_import_symbol=symbol,
                    category=cat,
                    is_external=is_ext,
                    line_number=node.lineno,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = node.module or ""
        for alias in node.names:
            if alias.name == "*":
                cat = ImportCategory.WILDCARD
                imp_type = "star"
                raw = f"from {module} import *"
                resolved = False
            else:
                cat = ImportCategory.CONDITIONAL if self.in_conditional else ImportCategory.STATIC
                imp_type = "conditional" if self.in_conditional else "static"
                raw = f"from {module} import {alias.name}"
                resolved = True

            symbol = f"{module}.{alias.name}" if module else alias.name
            target, is_ext = self._resolve_python_import(module or alias.name)
            self.edges.append(
                ImportEdge(
                    target=target,
                    resolved=resolved and not is_ext,
                    import_type=imp_type,
                    source_path=self.source_path,
                    raw_import_symbol=raw,
                    category=cat,
                    is_external=is_ext,
                    line_number=node.lineno,
                )
            )

    def visit_Call(self, node: ast.Call):
        # Detect dynamic imports like importlib.import_module("x") or __import__("y")
        is_dynamic = False
        module_name = ""

        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            is_dynamic = True
            if node.args and isinstance(node.args[0], ast.Constant):
                module_name = str(node.args[0].value)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
            is_dynamic = True
            if node.args and isinstance(node.args[0], ast.Constant):
                module_name = str(node.args[0].value)

        if is_dynamic and module_name:
            target, is_ext = self._resolve_python_import(module_name)
            self.edges.append(
                ImportEdge(
                    target=target,
                    resolved=False,  # dynamic imports marked resolved=false per Part A spec
                    import_type="dynamic",
                    source_path=self.source_path,
                    raw_import_symbol=f"dynamic:{module_name}",
                    category=ImportCategory.DYNAMIC,
                    is_external=is_ext,
                    line_number=node.lineno,
                )
            )
        self.generic_visit(node)

    def _resolve_python_import(self, symbol: str) -> Tuple[str, bool]:
        """Resolves Python module symbol to relative repo path or external dependency."""
        if not symbol:
            return "unknown", True

        rel_path = symbol.replace(".", "/") + ".py"
        init_path = symbol.replace(".", "/") + "/__init__.py"

        # 1. Check relative to source_path directory first (intra-package resolution)
        source_dir = str(Path(self.source_path).parent).replace("\\", "/")
        if source_dir and source_dir != ".":
            same_dir_rel = f"{source_dir}/{rel_path}"
            same_dir_init = f"{source_dir}/{init_path}"
            if same_dir_rel in self.all_repo_files:
                return same_dir_rel, False
            if same_dir_init in self.all_repo_files:
                return same_dir_init, False

        # 2. Check root-relative path
        if rel_path in self.all_repo_files:
            return rel_path, False
        if init_path in self.all_repo_files:
            return init_path, False

        # 3. Check for src/ prefix
        if f"src/{rel_path}" in self.all_repo_files:
            return f"src/{rel_path}", False
        if f"src/{init_path}" in self.all_repo_files:
            return f"src/{init_path}", False

        # 4. Deterministic suffix matches in repo files
        for repo_file in sorted(self.all_repo_files):
            if repo_file.endswith("/" + rel_path) or repo_file == rel_path:
                return repo_file, False
            if repo_file.endswith("/" + init_path) or repo_file == init_path:
                return repo_file, False

        top_package = symbol.split(".")[0]
        return top_package, True
