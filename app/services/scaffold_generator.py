"""Scaffold Generation and Fill-the-Blanks Verification Engine (Prompt 25).

Generates scaffolded source code files with function/method bodies stubbed out
while preserving imports, class structures, constants, type annotations, signatures,
and docstrings. Provides targeted grading evaluating only the blanked regions.
"""

from __future__ import annotations

import ast
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from app.parser.python_parser import PythonLanguageParser
from app.services.structural_verifier import StructuralVerifier, SymbolDefinition


class PythonScaffoldVisitor(ast.NodeTransformer):
    """
    AST Transformer that removes function and method executable bodies,
    preserving docstrings, signatures, decorators, type hints, and top-level constants.
    """

    def __init__(self):
        super().__init__()
        self.blanked_functions: List[Dict[str, Any]] = []
        self.total_functions: int = 0
        self.enclosing_class: Optional[str] = None

    def _is_empty_or_trivial_stub(self, body: List[ast.stmt]) -> bool:
        """Determines if a function body already has no real executable logic."""
        meaningful_stmts = []
        for i, stmt in enumerate(body):
            # First statement can be docstring
            if i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                continue
            meaningful_stmts.append(stmt)

        if not meaningful_stmts:
            return True
        if len(meaningful_stmts) == 1:
            s = meaningful_stmts[0]
            if isinstance(s, ast.Pass):
                return True
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and s.value.value in (..., None):
                return True
            if isinstance(s, ast.Raise) and isinstance(s.exc, ast.Call):
                func = s.exc.func
                if isinstance(func, ast.Name) and func.id in ("NotImplementedError", "NotImplemented"):
                    return True
        return False

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        prev_class = self.enclosing_class
        self.enclosing_class = node.name
        self.generic_visit(node)
        self.enclosing_class = prev_class
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._process_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._process_function(node, is_async=True)

    def _process_function(
        self,
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        is_async: bool = False,
    ) -> ast.AST:
        self.total_functions += 1
        docstring = ast.get_docstring(node)
        args_list = [a.arg for a in node.args.args]
        is_trivial = self._is_empty_or_trivial_stub(node.body)

        full_name = f"{self.enclosing_class}.{node.name}" if self.enclosing_class else node.name
        kind = "method" if self.enclosing_class else "function"

        # Record blanked function metadata
        self.blanked_functions.append({
            "name": node.name,
            "full_name": full_name,
            "class_name": self.enclosing_class,
            "kind": kind,
            "is_async": is_async,
            "args": args_list,
            "has_docstring": bool(docstring),
            "docstring": docstring or "",
            "lineno": getattr(node, "lineno", 1),
            "is_trivial": is_trivial,
        })

        # Reconstruct body: keep docstring if present, then add pass statement
        new_body: List[ast.stmt] = []
        if docstring:
            new_body.append(ast.Expr(value=ast.Constant(value=docstring)))
        new_body.append(ast.Pass())

        node.body = new_body
        return node


class ScaffoldGenerator:
    """Service generating scaffolded files with blanked bodies and evaluating fill submissions."""

    PYTHON_EXTENSIONS: Set[str] = {".py", ".pyi", ".pyw"}
    NON_PYTHON_REASON: str = (
        "Fill the Blanks mode is currently available for Python files. "
        "Try Guess It or Just Read It for this file instead."
    )

    @classmethod
    def is_python_file(
        cls,
        language: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> bool:
        """
        Determines whether the target file / language is Python.
        Checks file extension first when available, then language string.
        """
        if file_path:
            from pathlib import Path
            ext = Path(file_path).suffix.lower()
            if ext:
                return ext in cls.PYTHON_EXTENSIONS
        if language:
            norm_lang = language.lower().strip()
            return norm_lang in ("python", "py", "python3")
        return True

    @classmethod
    def generate_scaffold(
        cls,
        code: str,
        language: str = "python",
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generates scaffolded code from source code.
        Replaces executable function bodies with stubs while keeping signatures and classes intact.
        Returns detailed scaffold analysis dictionary.
        """
        if not code or not code.strip():
            return {
                "scaffold_code": code or "",
                "has_scaffold": False,
                "blanked_functions": [],
                "total_functions": 0,
                "blanked_count": 0,
                "reason": "File is empty or contains no source code.",
            }

        # Check if file is Python before attempting Python-specific AST parsing
        if not cls.is_python_file(language=language, file_path=file_path):
            return {
                "scaffold_code": code,
                "has_scaffold": False,
                "blanked_functions": [],
                "total_functions": 0,
                "blanked_count": 0,
                "reason": cls.NON_PYTHON_REASON,
            }

        return cls._generate_python_scaffold(code, file_path)

    @classmethod
    def _generate_python_scaffold(cls, code: str, file_path: Optional[str] = None) -> Dict[str, Any]:
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            # If the raw file cannot be parsed, fallback to generic line-based or unparsed
            return {
                "scaffold_code": code,
                "has_scaffold": False,
                "blanked_functions": [],
                "total_functions": 0,
                "blanked_count": 0,
                "reason": f"Syntax error in source file: {e}",
            }

        visitor = PythonScaffoldVisitor()
        modified_tree = visitor.visit(tree)
        ast.fix_missing_locations(modified_tree)

        blanked = visitor.blanked_functions
        total_funcs = visitor.total_functions
        # Non-trivial functions that actually had logic removed
        meaningful_blanked = [f for f in blanked if not f["is_trivial"]]

        if total_funcs == 0:
            return {
                "scaffold_code": code,
                "has_scaffold": False,
                "blanked_functions": [],
                "total_functions": 0,
                "blanked_count": 0,
                "reason": "File contains only constants, type declarations, or exports with no function bodies to scaffold.",
            }

        if len(meaningful_blanked) == 0:
            return {
                "scaffold_code": code,
                "has_scaffold": False,
                "blanked_functions": blanked,
                "total_functions": total_funcs,
                "blanked_count": 0,
                "reason": "All functions in this file are already abstract or empty stubs.",
            }

        try:
            scaffold_code = ast.unparse(modified_tree)
        except Exception:
            scaffold_code = code

        return {
            "scaffold_code": scaffold_code,
            "has_scaffold": True,
            "blanked_functions": blanked,
            "total_functions": total_funcs,
            "blanked_count": len(blanked),
            "meaningful_blanked_count": len(meaningful_blanked),
            "reason": None,
        }

    @classmethod
    def _generate_generic_scaffold(
        cls, code: str, language: str, file_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generic regex/block-based fallback for non-Python files (JS, TS, Go, Rust, C++)."""
        # Pattern matching function declarations with curly brace blocks
        func_pattern = re.compile(
            r"((?:async\s+)?(?:function\s+\w+|\w+\s*\([^)]*\)\s*(?::\s*[\w<>]+)?\s*=>|(?:public|private|protected|static|export|fn|func|def)\s+[\w\s:<>,*&]+\s*\([^)]*\)\s*(?:->\s*[\w<>]+)?)\s*\{([^}]*)\}",
            re.MULTILINE,
        )

        matches = list(func_pattern.finditer(code))
        if not matches:
            return {
                "scaffold_code": code,
                "has_scaffold": False,
                "blanked_functions": [],
                "total_functions": 0,
                "blanked_count": 0,
                "reason": f"No extractable function bodies found in {language} file.",
            }

        blanked_functions = []
        modified_code = code

        for idx, match in enumerate(reversed(matches)):
            sig = match.group(1).strip()
            body = match.group(2)
            if len(body.strip()) > 0 and "TODO" not in body:
                blanked_functions.append({
                    "name": f"function_{len(matches) - idx}",
                    "signature": sig,
                    "kind": "function",
                })
                # Replace body with TODO stub
                stub_replacement = f"{sig} {{\n    // TODO: implement\n    return null;\n}}"
                start, end = match.span()
                modified_code = modified_code[:start] + stub_replacement + modified_code[end:]

        return {
            "scaffold_code": modified_code,
            "has_scaffold": len(blanked_functions) > 0,
            "blanked_functions": blanked_functions,
            "total_functions": len(matches),
            "blanked_count": len(blanked_functions),
            "reason": None if blanked_functions else "No non-empty function bodies found to scaffold.",
        }

    @classmethod
    def grade_fill_blanks(
        cls,
        submitted_code: str,
        scaffold_info: Dict[str, Any],
        language: str = "python",
    ) -> Dict[str, Any]:
        """
        Grades a 'Fill the Blanks' submission by scoping evaluation ONLY to the blanked regions.
        Does not require the user to retype given scaffold structures or constants.
        """
        norm_lang = (language or "python").lower().strip()
        blanked_functions = scaffold_info.get("blanked_functions", [])

        if not submitted_code or not submitted_code.strip():
            return {
                "passed": False,
                "is_verified": False,
                "structurally_verified": False,
                "error_message": "Submission is empty.",
                "present_symbols": [],
                "missing_symbols": [{"expected": f["name"], "kind": f.get("kind", "function")} for f in blanked_functions],
                "extra_symbols": [],
                "total_blanked": len(blanked_functions),
                "blanked_evaluated": len(blanked_functions),
                "implemented_count": 0,
                "blank_details": [{"name": f["name"], "status": "missing", "reason": "Empty submission"} for f in blanked_functions],
                "grading_method": "fill_the_blanks",
            }

        if norm_lang in ("python", "py", "python3"):
            return cls._grade_python_fill_blanks(submitted_code, blanked_functions)
        else:
            return cls._grade_generic_fill_blanks(submitted_code, blanked_functions)

    @classmethod
    def _grade_python_fill_blanks(
        cls,
        submitted_code: str,
        blanked_functions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        try:
            tree = ast.parse(submitted_code)
        except SyntaxError as e:
            return {
                "passed": False,
                "is_verified": False,
                "structurally_verified": False,
                "error_message": f"Syntax error in submission: {e}",
                "present_symbols": [],
                "missing_symbols": [{"expected": f["name"], "kind": f.get("kind", "function")} for f in blanked_functions],
                "extra_symbols": [],
                "total_blanked": len(blanked_functions),
                "blanked_evaluated": len(blanked_functions),
                "implemented_count": 0,
                "blank_details": [{"name": f["name"], "status": "missing", "reason": f"Syntax error: {e}"} for f in blanked_functions],
                "grading_method": "fill_the_blanks",
            }

        # Index submitted functions by both qualified full_name and simple name
        visitor = PythonScaffoldVisitor()
        visitor.visit(tree)
        submitted_funcs: Dict[str, Dict[str, Any]] = {}
        for f in visitor.blanked_functions:
            if f.get("full_name"):
                submitted_funcs[f["full_name"]] = f
            if f["name"] not in submitted_funcs:
                submitted_funcs[f["name"]] = f

        present: List[Dict[str, Any]] = []
        missing: List[Dict[str, Any]] = []

        for expected in blanked_functions:
            full_name = expected.get("full_name") or expected["name"]
            simple_name = expected["name"]
            
            sub_meta = submitted_funcs.get(full_name) or submitted_funcs.get(simple_name)
            if sub_meta:
                # If the function was non-trivial in source, user must have filled in real body (not just pass/stub)
                if not sub_meta["is_trivial"] or expected["is_trivial"]:
                    present.append({
                        "matched": {
                            "name": full_name,
                            "kind": expected.get("kind", "function"),
                            "args": expected.get("args", []),
                        },
                        "status": "implemented",
                    })
                else:
                    missing.append({
                        "expected": {
                            "name": full_name,
                            "kind": expected.get("kind", "function"),
                            "args": expected.get("args", []),
                        },
                        "reason": "Function body is still an empty pass / stub placeholder.",
                    })
            else:
                missing.append({
                    "expected": {
                        "name": full_name,
                        "kind": expected.get("kind", "function"),
                        "args": expected.get("args", []),
                    },
                    "reason": "Function is missing from submission.",
                })

        all_implemented = (len(missing) == 0) and (len(blanked_functions) > 0)
        implemented_count = len(present)
        total_count = len(blanked_functions)

        err_msg = None
        if not all_implemented:
            if missing:
                missing_names = [m["expected"]["name"] for m in missing]
                err_msg = f"{len(missing)} of {total_count} blanked function(s) not yet implemented: {', '.join(missing_names)}"
            else:
                err_msg = "No blanked functions were implemented."

        blank_details = []
        for p in present:
            blank_details.append({
                "name": p["matched"]["name"],
                "status": "implemented",
                "reason": None,
            })
        for m in missing:
            status = "unimplemented_stub" if "stub" in (m.get("reason") or "").lower() else "missing"
            blank_details.append({
                "name": m["expected"]["name"],
                "status": status,
                "reason": m.get("reason"),
            })

        return {
            "passed": all_implemented,
            "is_verified": all_implemented,
            "structurally_verified": all_implemented,
            "error_message": err_msg,
            "present_symbols": present,
            "missing_symbols": missing,
            "extra_symbols": [],
            "total_blanked": total_count,
            "blanked_evaluated": total_count,
            "implemented_count": implemented_count,
            "blank_details": blank_details,
            "grading_method": "fill_the_blanks",
        }

    @classmethod
    def _grade_generic_fill_blanks(
        cls,
        submitted_code: str,
        blanked_functions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        present = []
        missing = []
        blank_details = []
        for f in blanked_functions:
            fname = f.get("name", "")
            if fname and fname in submitted_code and "TODO: implement" not in submitted_code:
                present.append({"matched": {"name": fname, "kind": "function"}})
                blank_details.append({"name": fname, "status": "implemented", "reason": None})
            else:
                missing.append({"expected": {"name": fname, "kind": "function"}})
                blank_details.append({"name": fname, "status": "unimplemented_stub", "reason": "Contains TODO stub"})

        passed = len(missing) == 0 and len(blanked_functions) > 0
        return {
            "passed": passed,
            "is_verified": passed,
            "structurally_verified": passed,
            "error_message": None if passed else "Some blanked regions still contain TODO stubs.",
            "present_symbols": present,
            "missing_symbols": missing,
            "extra_symbols": [],
            "total_blanked": len(blanked_functions),
            "blanked_evaluated": len(blanked_functions),
            "implemented_count": len(present),
            "blank_details": blank_details,
            "grading_method": "fill_the_blanks",
        }
