"""Progressive Hint Generation Engine for Milestone Reconstruction.

Generates tiered, pedagogical hints sourced from real architectural metadata (graph_data,
AST dependency tiers, domain distributions) without leaking literal code.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.structural_verifier import StructuralVerifier


class HintLeakError(Exception):
    """Raised if Hint 1 accidentally leaks an exact expected symbol name."""
    pass


class HintEngine:
    """Engine for generating progressive, non-leaking architectural hints."""

    # 3 Real Tone-Aligned Confirmation Copy Variants
    CONFIRM_COPY_VARIANTS = [
        "Take another few minutes — this is where the mental model actually crystallizes. Still want a conceptual hint?",
        "Wrestling with the boundary invariants is where the learning happens. Ready for a high-level nudge?",
        "Pause and trace the imports one more time. Need a high-level architectural hint?",
    ]
    SELECTED_HINT_1_CONFIRM = CONFIRM_COPY_VARIANTS[0]

    CONFIRM_HINT_2_COPY = (
        "You've already explored the conceptual structure. Ready to reveal specific missing symbol targets?"
    )

    CONFIRM_REVEAL_COPY = (
        "Revealing the reference implementation will permanently mark this milestone as revealed. "
        "Are you sure you want to view the reference structure?"
    )

    @classmethod
    def get_hint_1(
        cls,
        graph_data: Dict[str, Any],
        milestone_tier: int,
        milestone_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generates Hint 1: Conceptual architectural guidance only.
        References real domain, dependency direction, and architectural role.
        Guaranteed zero exact symbol leaks.
        """
        nodes = graph_data.get("nodes", []) if isinstance(graph_data, dict) else []
        edges = graph_data.get("edges", []) if isinstance(graph_data, dict) else []

        tier_nodes = [n for n in nodes if n.get("tier") == milestone_tier]
        domains: Set[str] = {n.get("domain", n.get("type", "core")).upper() for n in tier_nodes}
        domain_str = ", ".join(sorted(domains)) if domains else "CORE"

        # Outbound dependencies (what this tier calls/imports)
        tier_node_ids = {n.get("id") for n in tier_nodes}
        outbound_targets = {
            e.get("target") for e in edges if e.get("source") in tier_node_ids
        }
        # Inbound dependencies (what depends on this tier)
        inbound_sources = {
            e.get("source") for e in edges if e.get("target") in tier_node_ids
        }

        role_desc = ""
        if milestone_meta and milestone_meta.get("architectural_role"):
            role_desc = f" ({milestone_meta['architectural_role']})"

        if milestone_tier == 0:
            hint_text = (
                f"Milestone {milestone_tier} forms the foundation layer{role_desc} operating in the {domain_str} domain. "
                f"Modules in this layer should have minimal or no external dependencies within the project, acting as "
                f"leaf nodes that higher tiers rely on. Focus on defining the primary configuration structures and core "
                f"initialization abstractions required by upstream orchestrators."
            )
        else:
            in_str = f"higher tiers (such as Tier {milestone_tier + 1})" if inbound_sources else "top-level entry points"
            hint_text = (
                f"Milestone {milestone_tier}{role_desc} operates primarily within the {domain_str} domain. "
                f"It bridges lower foundation tiers (Tier {milestone_tier - 1}) into {in_str}. "
                f"Ensure your implementation correctly encapsulates the domain boundaries and exposes clean "
                f"callable contracts for upper layers to orchestrate."
            )

        # Threat Model Verification: Assert that Hint 1 contains zero exact expected symbol names
        expected_symbols = StructuralVerifier.extract_expected_symbols_from_graph(graph_data, milestone_tier)
        cls.verify_hint_1_no_leaks(hint_text, expected_symbols)

        return hint_text

    @classmethod
    def verify_hint_1_no_leaks(
        cls, hint_text: str, expected_symbols: List[Dict[str, Any]]
    ) -> None:
        """
        Strictly verifies that Hint 1 does not leak any exact expected symbol names.
        Raises HintLeakError if an exact word match is found.
        """
        normalized_hint = hint_text.lower()
        for sym in expected_symbols:
            name = sym.get("name", "")
            if not name or len(name) < 3:
                continue
            # Check for exact word boundary match
            pattern = rf"\b{re.escape(name.lower())}\b"
            if re.search(pattern, normalized_hint):
                raise HintLeakError(
                    f"Hint 1 leak violation: Exact expected symbol '{name}' found in conceptual hint text: {hint_text}"
                )

    @classmethod
    def get_hint_2(
        cls,
        graph_data: Dict[str, Any],
        milestone_tier: int,
        missing_symbols: Optional[List[Dict[str, Any]]] = None,
        milestone_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generates Hint 2: Specific symbol targets and relevant file paths from real AST diff.
        Zero literal code implementation.
        """
        nodes = graph_data.get("nodes", []) if isinstance(graph_data, dict) else []
        tier_nodes = [n for n in nodes if n.get("tier") == milestone_tier]
        included_files = [n.get("path", n.get("id")) for n in tier_nodes if n.get("path") or n.get("id")]

        files_str = ", ".join(f"`{f}`" for f in included_files[:3]) if included_files else "milestone source files"

        if missing_symbols and len(missing_symbols) > 0:
            sym_items = []
            for s in missing_symbols[:5]:
                mat = s.get("expected") or s
                name = mat.get("name", "") if isinstance(mat, dict) else str(mat)
                kind = mat.get("kind", "symbol") if isinstance(mat, dict) else "symbol"
                sym_items.append(f"`{name}` ({kind})")
            syms_str = ", ".join(sym_items)
            return (
                f"Target Files: {files_str}. Missing AST contracts to declare: {syms_str}. "
                f"Declare these exact signatures in your workspace. (Do not write the full implementation logic; "
                f"structural declarations are sufficient for verification)."
            )
        else:
            expected_symbols = StructuralVerifier.extract_expected_symbols_from_graph(graph_data, milestone_tier)
            sym_items = [f"`{s.get('name')}` ({s.get('kind', 'symbol')})" for s in expected_symbols[:5]]
            syms_str = ", ".join(sym_items) if sym_items else "primary exported classes and functions"
            return (
                f"Target Files: {files_str}. Key required contracts: {syms_str}. "
                f"Verify that all class definitions and method signatures match these expected AST interfaces."
            )

    @classmethod
    def get_reference_implementation(
        cls,
        graph_data: Dict[str, Any],
        milestone_tier: int,
        language: str = "python",
    ) -> Dict[str, Any]:
        """
        Returns reference architectural skeleton for the milestone when explicitly revealed.
        """
        expected_symbols = StructuralVerifier.extract_expected_symbols_from_graph(graph_data, milestone_tier)
        nodes = graph_data.get("nodes", []) if isinstance(graph_data, dict) else []
        tier_nodes = [n for n in nodes if n.get("tier") == milestone_tier]

        skeleton_lines = [
            f"# Milestone {milestone_tier} Reference Structural Implementation",
            "# Generated from verified static AST syntax tree",
            "",
        ]

        classes = [s for s in expected_symbols if s.get("kind") == "class"]
        funcs = [s for s in expected_symbols if s.get("kind") == "function"]

        for c in classes:
            c_name = c.get("name", "Class")
            skeleton_lines.append(f"class {c_name}:")
            skeleton_lines.append("    \"\"\"Reference architectural contract.\"\"\"")
            skeleton_lines.append("    def __init__(self):")
            skeleton_lines.append("        pass\n")

        for f in funcs:
            f_name = f.get("name", "func")
            args = f.get("args") or []
            args_str = ", ".join(args) if args else ""
            skeleton_lines.append(f"def {f_name}({args_str}):")
            skeleton_lines.append("    \"\"\"Exported module function.\"\"\"")
            skeleton_lines.append("    return None\n")

        return {
            "milestone_tier": milestone_tier,
            "included_files": [n.get("path", n.get("id")) for n in tier_nodes],
            "expected_symbols": expected_symbols,
            "reference_code": "\n".join(skeleton_lines),
        }
