"""TLA+ Presence Detection Parser (Layer 2 core)."""

import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from app.parser.base import BaseLanguageParser
from app.parser.schema import FileNode, ImportCategory, ImportEdge

TLA_STDLIB_MODULES = {
    "Naturals",
    "Integers",
    "Reals",
    "Sequences",
    "FiniteSets",
    "Bags",
    "TLC",
    "RealTime",
    "Json",
    "Randomization",
    "TLAPS",
}


class TlaLanguageParser(BaseLanguageParser):
    """
    TLA+ presence detection parser.

    Extracts minimal structural metadata:
    - Module name from header line (`---- MODULE ModuleName ----`)
    - `EXTENDS` dependencies (resolved against in-repo `.tla` modules)
    - Associated `.cfg` files linked as metadata

    Missing headers do NOT trigger ParseError; files are recorded with empty module name.
    """

    @property
    def language_name(self) -> str:
        return "tla+"

    @property
    def file_extensions(self) -> Set[str]:
        return {".tla"}

    def parse_single_file(
        self, file_path: str, code_content: str, all_repo_files: Set[str]
    ) -> Tuple[FileNode, List[ImportEdge]]:
        # 1. Module name extraction
        module_name = self._extract_module_name(code_content)

        # 2. EXTENDS module extraction
        extended_modules = self._extract_extends(code_content)

        # 3. Import edge building & resolution
        edges: List[ImportEdge] = []
        for ext_mod in extended_modules:
            target_path, is_ext, resolved = self._resolve_extended_module(
                ext_mod, file_path, all_repo_files
            )
            edges.append(
                ImportEdge(
                    target=target_path,
                    resolved=resolved,
                    import_type="static",
                    source_path=file_path,
                    raw_import_symbol=f"EXTENDS {ext_mod}",
                    category=ImportCategory.STATIC,
                    is_external=is_ext,
                )
            )

        # 4. Associated .cfg file discovery & linking
        exports: List[str] = []
        if module_name:
            exports.append(f"module:{module_name}")

        cfg_paths = self._find_associated_configs(file_path, module_name, all_repo_files)
        for cfg_p in cfg_paths:
            exports.append(f"config:{cfg_p}")

        node = FileNode(
            path=file_path,
            language=self.language_name,
            entry_point=False,
            exports=exports,
            classes=[],
            functions=[],
        )

        return node, edges

    def _extract_module_name(self, code_content: str) -> str:
        for line in code_content.splitlines():
            stripped = line.strip()
            match = re.match(r"^[-\=]{3,}\s*MODULE\s+([A-Za-z0-9_]+)", stripped)
            if match:
                return match.group(1)
        return ""

    def _extract_extends(self, code_content: str) -> List[str]:
        extended_modules: List[str] = []
        lines = code_content.splitlines()
        in_extends = False
        extends_text = ""

        for line in lines:
            # Strip comments
            clean_line = re.sub(r"\\\*.*$", "", line)
            clean_line = re.sub(r"\(\*.*?\*\)", "", clean_line)

            if re.search(r"\bEXTENDS\b", clean_line):
                in_extends = True
                parts = re.split(r"\bEXTENDS\b", clean_line, maxsplit=1)
                extends_text += " " + parts[1]
                if not clean_line.rstrip().endswith(","):
                    pass
            elif in_extends:
                if re.search(
                    r"\b(VARIABLES|VARIABLE|CONSTANTS|CONSTANT|ASSUME|THEOREM|INSTANCE|LOCAL|RECURSIVE)\b",
                    clean_line,
                ) or re.match(r"^[-\=]{3,}", clean_line):
                    in_extends = False
                else:
                    extends_text += " " + clean_line
                    if not clean_line.rstrip().endswith(","):
                        in_extends = False

        tokens = re.findall(r"\b([A-Za-z0-9_]+)\b", extends_text)
        keywords = {
            "EXTENDS",
            "MODULE",
            "VARIABLES",
            "VARIABLE",
            "CONSTANTS",
            "CONSTANT",
            "ASSUME",
            "THEOREM",
            "INSTANCE",
            "LOCAL",
            "RECURSIVE",
        }
        for token in tokens:
            if token not in keywords and token not in extended_modules:
                extended_modules.append(token)

        return extended_modules

    def _resolve_extended_module(
        self, ext_mod: str, source_file: str, all_repo_files: Set[str]
    ) -> Tuple[str, bool, bool]:
        """
        Resolves extended module against in-repo .tla files or stdlib/external modules.
        Returns (target_path, is_external, resolved).
        """
        source_dir = os.path.dirname(source_file)

        # Check same directory first
        same_dir_candidate = os.path.join(source_dir, f"{ext_mod}.tla").replace("\\", "/")
        if same_dir_candidate in all_repo_files:
            return same_dir_candidate, False, True

        # Search any file in all_repo_files matching <ext_mod>.tla
        for path in all_repo_files:
            norm_path = path.replace("\\", "/")
            if (
                norm_path.endswith(f"/{ext_mod}.tla")
                or norm_path == f"{ext_mod}.tla"
                or Path(path).stem == ext_mod
            ):
                if norm_path.endswith(".tla"):
                    return norm_path, False, True

        # Check stdlib
        if ext_mod in TLA_STDLIB_MODULES:
            return ext_mod, True, False

        # Missing in-repo module
        return ext_mod, True, False

    def _find_associated_configs(
        self, source_file: str, module_name: str, all_repo_files: Set[str]
    ) -> List[str]:
        """Discovers associated .cfg files for the TLA+ spec."""
        cfg_matches: List[str] = []
        source_dir = os.path.dirname(source_file)
        stem = Path(source_file).stem

        # Check stem.cfg in same directory
        same_dir_stem_cfg = os.path.join(source_dir, f"{stem}.cfg").replace("\\", "/")
        if same_dir_stem_cfg in all_repo_files:
            cfg_matches.append(same_dir_stem_cfg)

        # Check module_name.cfg in same directory if module_name != stem
        if module_name and module_name != stem:
            same_dir_mod_cfg = os.path.join(source_dir, f"{module_name}.cfg").replace("\\", "/")
            if same_dir_mod_cfg in all_repo_files and same_dir_mod_cfg not in cfg_matches:
                cfg_matches.append(same_dir_mod_cfg)

        # Also search repo-wide for matching cfg files if not found yet
        if not cfg_matches:
            for path in all_repo_files:
                if path.endswith(".cfg"):
                    path_normalized = path.replace("\\", "/")
                    path_stem = Path(path).stem
                    if path_stem in {stem, module_name}:
                        cfg_matches.append(path_normalized)

        return sorted(cfg_matches)
