"""Structural Verification Engine for Milestone Code Submissions.

Reuses existing parser infrastructure (app/parser/) to statically analyze
user-submitted code against milestone expected symbol tables.
User code is parsed strictly as static AST, never executed, eval'd, or run.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from app.parser.python_parser import PythonLanguageParser
from app.parser.registry import ParserRegistry
from app.utils.file_filter import MAX_FILE_SIZE_BYTES


class StructuralVerificationError(Exception):
    """Raised when code submission fails safety checks or exceeds size limits."""
    pass


class SymbolDefinition:
    """Standardized representation of a code symbol for structural matching."""

    def __init__(
        self,
        name: str,
        kind: str = "function",  # "function", "class", "method", "variable"
        arg_count: Optional[int] = None,
        args: Optional[List[str]] = None,
        is_async: bool = False,
        is_stub: bool = False,
    ):
        self.name = name
        self.kind = kind.lower()
        self.arg_count = arg_count
        self.args = args or []
        self.is_async = is_async
        self.is_stub = is_stub

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
        }
        if self.arg_count is not None:
            d["arg_count"] = self.arg_count
        if self.args:
            d["args"] = self.args
        if self.is_stub:
            d["is_stub"] = True
        return d

    def matches(self, other: SymbolDefinition) -> bool:
        """Matches name + kind + rough signature shape (arg count)."""
        if self.name != other.name:
            return False

        # Kind matching (class vs function/method)
        if self.kind == "class" and other.kind != "class":
            return False
        if self.kind in ("function", "method") and other.kind not in ("function", "method"):
            return False

        # Rough signature shape (arg count) matching if specified on either side
        if self.arg_count is not None and other.arg_count is not None:
            # If one is a method (e.g. has self/cls parameter), check exact or offset by 1
            if self.arg_count == other.arg_count:
                return True
            if "self" in self.args or "cls" in self.args:
                if self.arg_count - 1 == other.arg_count:
                    return True
            if "self" in other.args or "cls" in other.args:
                if other.arg_count - 1 == self.arg_count:
                    return True
            return False

        return True


def _is_stub_body(body: List[ast.stmt]) -> bool:
    """
    Checks if a function or method body consists solely of stub/placeholder statements:
    - pass
    - ... (Ellipsis) or None
    - docstring only
    - raise NotImplementedError or raise NotImplementedError(...)
    - docstring followed by any of the above
    """
    meaningful_stmts = []
    for i, stmt in enumerate(body):
        # First statement can be a docstring
        if i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            continue
        meaningful_stmts.append(stmt)

    if not meaningful_stmts:
        return True

    def _is_trivial_stmt(s: ast.stmt) -> bool:
        if isinstance(s, ast.Pass):
            return True
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant):
            if s.value.value in (..., None) or isinstance(s.value.value, str):
                return True
        if isinstance(s, ast.Raise):
            if isinstance(s.exc, ast.Call) and isinstance(s.exc.func, ast.Name) and s.exc.func.id in ("NotImplementedError", "NotImplemented"):
                return True
            if isinstance(s.exc, ast.Name) and s.exc.id in ("NotImplementedError", "NotImplemented"):
                return True
        return False

    return all(_is_trivial_stmt(s) for s in meaningful_stmts)


class StructuralVerifier:
    """Engine verifying user-submitted code against milestone symbol tables."""

    def __init__(self):
        self.parser_registry = ParserRegistry()
        self.python_parser = PythonLanguageParser()

    @staticmethod
    def extract_expected_symbols_from_graph(
        graph_data: Dict[str, Any], milestone_tier: int
    ) -> List[Dict[str, Any]]:
        """
        Extracts the real expected symbol table for a milestone tier
        from Layer 4 / Layer 7 graph output data.
        """
        expected_symbols: List[Dict[str, Any]] = []
        seen_names: Set[str] = set()

        nodes = graph_data.get("nodes", [])
        for node in nodes:
            if node.get("tier") == milestone_tier:
                exports = node.get("exports", [])
                for exp in exports:
                    if isinstance(exp, str) and exp not in seen_names:
                        seen_names.add(exp)
                        kind = "class" if exp and exp[0].isupper() and "_" not in exp else "function"
                        expected_symbols.append({
                            "name": exp,
                            "kind": kind,
                            "source_file": node.get("id"),
                        })
                    elif isinstance(exp, dict) and exp.get("name") and exp["name"] not in seen_names:
                        seen_names.add(exp["name"])
                        expected_symbols.append({
                            "name": exp["name"],
                            "kind": exp.get("kind", "symbol"),
                            "source_file": node.get("id"),
                            "args": exp.get("args", []),
                        })

                symbols = node.get("symbols", [])
                for sym in symbols:
                    if isinstance(sym, str) and sym not in seen_names:
                        seen_names.add(sym)
                        kind = "class" if sym and sym[0].isupper() and "_" not in sym else "function"
                        expected_symbols.append({
                            "name": sym,
                            "kind": kind,
                            "source_file": node.get("id"),
                        })
                    elif isinstance(sym, dict) and sym.get("name") and sym["name"] not in seen_names:
                        seen_names.add(sym["name"])
                        expected_symbols.append({
                            "name": sym["name"],
                            "kind": sym.get("kind", "symbol"),
                            "source_file": node.get("id"),
                            "args": sym.get("args", []),
                        })
        return expected_symbols

    def extract_symbols_from_code(
        self, code: str, language: str = "python"
    ) -> Tuple[List[SymbolDefinition], bool, Optional[str]]:
        """
        Parses submitted code and extracts symbol definitions (classes, functions, methods).
        Enforces static AST analysis only — never executes or evaluates code.
        """
        # Guard against DoS / oversized input
        code_bytes = code.encode("utf-8")
        if len(code_bytes) > MAX_FILE_SIZE_BYTES:
            raise StructuralVerificationError(
                f"Submitted code size ({len(code_bytes)} bytes) exceeds maximum limit of "
                f"{MAX_FILE_SIZE_BYTES} bytes (1MB)."
            )

        symbols: List[SymbolDefinition] = []

        if language.lower() in ("python", "py"):
            try:
                tree = ast.parse(code, filename="<submitted_code>")
            except SyntaxError as e:
                return [], False, f"SyntaxError: {e.msg} at line {e.lineno}"
            except Exception as e:
                return [], False, f"ParseError: {str(e)}"

            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    class_sym = SymbolDefinition(
                        name=node.name,
                        kind="class",
                    )
                    symbols.append(class_sym)

                    # Extract methods within class
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            arg_names = [a.arg for a in item.args.args]
                            # Count positional + keyword-only args
                            total_args = len(item.args.args) + len(item.args.kwonlyargs)
                            is_stub = _is_stub_body(item.body)
                            method_sym = SymbolDefinition(
                                name=item.name,
                                kind="method",
                                arg_count=total_args,
                                args=arg_names,
                                is_async=isinstance(item, ast.AsyncFunctionDef),
                                is_stub=is_stub,
                            )
                            symbols.append(method_sym)

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    arg_names = [a.arg for a in node.args.args]
                    total_args = len(node.args.args) + len(node.args.kwonlyargs)
                    is_stub = _is_stub_body(node.body)
                    func_sym = SymbolDefinition(
                        name=node.name,
                        kind="function",
                        arg_count=total_args,
                        args=arg_names,
                        is_async=isinstance(node, ast.AsyncFunctionDef),
                        is_stub=is_stub,
                    )
                    symbols.append(func_sym)

            return symbols, True, None

        else:
            # Fallback to parser registry for other languages
            ext_map = {
                "javascript": ".js",
                "typescript": ".ts",
                "go": ".go",
                "rust": ".rs",
                "java": ".java",
                "cpp": ".cpp",
                "shell": ".sh",
            }
            ext = ext_map.get(language.lower(), ".py")
            dummy_file = f"submission{ext}"
            parser = self.parser_registry.get_parser_for_file(dummy_file)
            if parser:
                try:
                    file_node, _ = parser.parse_single_file(dummy_file, code, {dummy_file})
                    for c in file_node.classes:
                        symbols.append(SymbolDefinition(name=c, kind="class"))
                    for f in file_node.functions:
                        symbols.append(SymbolDefinition(name=f, kind="function"))
                    for e in file_node.exports:
                        if not any(s.name == e for s in symbols):
                            symbols.append(SymbolDefinition(name=e, kind="function"))
                    return symbols, True, None
                except Exception as e:
                    return [], False, f"ParseError: {str(e)}"

            return [], False, f"Unsupported language: {language}"

    def verify(
        self,
        submitted_code: str,
        expected_symbols: Union[List[str], List[Dict[str, Any]], Dict[str, Any]],
        language: str = "python",
    ) -> Dict[str, Any]:
        """
        Statically verifies submitted code against expected symbols.

        Returns structured diff:
        - missing_symbols: Expected symbols not found (or stubbed out)
        - present_symbols: Expected symbols matched with real implementations
        - extra_symbols: Symbols present in code but not expected (informational)
        - stub_symbols: Expected symbols whose submitted implementation is a stub placeholder
        - structurally_verified: True if all expected symbols are present, non-stub, and code is syntactically valid
        """
        # 1. Normalize expected symbols into SymbolDefinition objects
        norm_expected: List[SymbolDefinition] = []
        if isinstance(expected_symbols, dict):
            raw_list = expected_symbols.get("exports", expected_symbols.get("symbols", []))
        elif isinstance(expected_symbols, list):
            raw_list = expected_symbols
        else:
            raw_list = []

        for item in raw_list:
            if isinstance(item, str):
                norm_expected.append(SymbolDefinition(name=item, kind="function"))
            elif isinstance(item, dict):
                norm_expected.append(
                    SymbolDefinition(
                        name=item.get("name", ""),
                        kind=item.get("kind", "function"),
                        arg_count=item.get("arg_count"),
                        args=item.get("args"),
                    )
                )

        # 2. Extract symbols from submitted code
        parsed_symbols, syntax_valid, error_msg = self.extract_symbols_from_code(
            submitted_code, language=language
        )

        if not syntax_valid:
            return {
                "structurally_verified": False,
                "syntax_valid": False,
                "error_message": error_msg,
                "missing_symbols": [e.to_dict() for e in norm_expected],
                "present_symbols": [],
                "extra_symbols": [],
                "stub_symbols": [],
            }

        # 3. Perform matching: name + kind + rough signature shape
        matched_parsed_indices: Set[int] = set()
        present_symbols: List[Dict[str, Any]] = []
        missing_symbols: List[Dict[str, Any]] = []
        stub_symbols: List[Dict[str, Any]] = []

        for exp in norm_expected:
            match_found = False
            for idx, sym in enumerate(parsed_symbols):
                if exp.matches(sym):
                    if sym.is_stub:
                        stub_symbols.append({
                            "expected": exp.to_dict(),
                            "matched": sym.to_dict(),
                            "reason": "Function body is a placeholder stub (pass, ..., docstring, or NotImplementedError)",
                        })
                        # Stubs cannot satisfy expected contracts
                        continue

                    matched_parsed_indices.add(idx)
                    present_symbols.append({
                        "expected": exp.to_dict(),
                        "matched": sym.to_dict(),
                    })
                    match_found = True
                    break

            if not match_found:
                exp_dict = exp.to_dict()
                stub_match = next((s for s in stub_symbols if s["expected"]["name"] == exp.name), None)
                if stub_match:
                    exp_dict["reason"] = stub_match["reason"]
                missing_symbols.append(exp_dict)

        # 4. Extra symbols (present in code, but not in expected table)
        extra_symbols: List[Dict[str, Any]] = [
            sym.to_dict()
            for idx, sym in enumerate(parsed_symbols)
            if idx not in matched_parsed_indices
        ]

        # Structurally verified if no missing expected symbols, no stub implementations, and at least one symbol verified
        is_verified = (len(missing_symbols) == 0 and len(norm_expected) > 0 and len(stub_symbols) == 0)

        err_msg = None
        if stub_symbols:
            stub_names = [s["expected"]["name"] for s in stub_symbols]
            err_msg = f"Function body for {', '.join(stub_names)} is an unimplemented placeholder stub (pass/.../docstring/NotImplementedError)."

        return {
            "structurally_verified": is_verified,
            "syntax_valid": True,
            "error_message": err_msg,
            "missing_symbols": missing_symbols,
            "present_symbols": present_symbols,
            "extra_symbols": extra_symbols,
            "stub_symbols": stub_symbols,
        }
