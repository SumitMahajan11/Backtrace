"""Java Static Structural Parser using javalang AST (Layer 2 core)."""

import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import javalang
from javalang.tree import ClassDeclaration, EnumDeclaration, InterfaceDeclaration, MethodDeclaration

from app.parser.base import BaseLanguageParser
from app.parser.schema import FileNode, ImportCategory, ImportEdge

CLASS_FOR_NAME_PATTERN = re.compile(r"""Class\s*\.\s*forName\s*\(\s*["']([^"']+)["']\s*\)""")


class JavaLanguageParser(BaseLanguageParser):
    """Java static structural parser using javalang AST library."""

    @property
    def language_name(self) -> str:
        return "java"

    @property
    def file_extensions(self) -> Set[str]:
        return {".java"}

    def parse_single_file(
        self, file_path: str, code_content: str, all_repo_files: Set[str]
    ) -> Tuple[FileNode, List[ImportEdge]]:
        classes: List[str] = []
        functions: List[str] = []
        exports: List[str] = []
        edges: List[ImportEdge] = []
        is_entry = False
        entry_type = None

        try:
            tree = javalang.parse.parse(code_content)
        except Exception as e:
            raise ValueError(f"Java parse error: {e}") from e

        if tree.imports:
            for imp in tree.imports:
                path_symbol = imp.path
                if imp.wildcard:
                    cat = ImportCategory.WILDCARD
                    imp_type = "star"
                    raw_symbol = f"import {path_symbol}.*"
                else:
                    cat = ImportCategory.STATIC
                    imp_type = "static"
                    raw_symbol = f"import {path_symbol}"

                target, is_ext = self._resolve_java_import(path_symbol, all_repo_files)
                line_no = getattr(imp, "position", None)
                line_num = line_no.line if line_no else None

                edges.append(
                    ImportEdge(
                        target=target,
                        resolved=(not is_ext and imp_type != "star"),
                        import_type=imp_type,
                        source_path=file_path,
                        raw_import_symbol=raw_symbol,
                        category=cat,
                        is_external=is_ext,
                        line_number=line_num,
                    )
                )

        for match in CLASS_FOR_NAME_PATTERN.finditer(code_content):
            dynamic_class = match.group(1)
            target, is_ext = self._resolve_java_import(dynamic_class, all_repo_files)
            edges.append(
                ImportEdge(
                    target=target,
                    resolved=False,
                    import_type="dynamic",
                    source_path=file_path,
                    raw_import_symbol=match.group(0),
                    category=ImportCategory.DYNAMIC,
                    is_external=is_ext,
                )
            )

        if tree.types:
            for type_decl in tree.types:
                if isinstance(type_decl, (ClassDeclaration, InterfaceDeclaration, EnumDeclaration)):
                    classes.append(type_decl.name)
                    exports.append(type_decl.name)

                    for body_item in type_decl.body:
                        if isinstance(body_item, MethodDeclaration):
                            functions.append(body_item.name)
                            if self._is_java_main_method(body_item):
                                is_entry = True
                                entry_type = "public_static_void_main"

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

    def _is_java_main_method(self, method: MethodDeclaration) -> bool:
        if method.name != "main":
            return False
        modifiers = set(method.modifiers or [])
        if "public" not in modifiers or "static" not in modifiers:
            return False
        if getattr(method.return_type, "name", None) != "void" and method.return_type is not None:
            return False
        if len(method.parameters) >= 1:
            first_param = method.parameters[0]
            param_type = getattr(first_param.type, "name", "")
            if param_type == "String":
                return True
        return False

    def _resolve_java_import(
        self, symbol: str, all_repo_files: Set[str]
    ) -> Tuple[str, bool]:
        rel_path = symbol.replace(".", "/") + ".java"
        for repo_file in all_repo_files:
            if repo_file.endswith(rel_path) or repo_file == rel_path:
                return repo_file, False
        return symbol, True
