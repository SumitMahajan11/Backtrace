"""Sequence Narration Engine & Prompt Engineering (Layer 6 Stage D)."""

from collections import Counter, defaultdict
import json
import re
from typing import Callable, Dict, List, Optional, Set, Tuple
from app.sequence.schema import (
    BuildStepNarrative,
    NodeMetadata,
    RefinedOrderingResult,
    ScoredFileEntry,
    ScoredOrderingResult,
    SequenceNarrationResult,
)


STAGE_D_SYSTEM_PROMPT = """You are a Senior Software Architect and Master Technical Educator.
Your task is to transform a topologically validated, confidence-scored software dependency sequence into an intuitive, step-by-step teaching narrative ("How to build/understand this repository from scratch").

CRITICAL PEDAGOGICAL RULES & GUARDRAILS:
1. STRICT SEQUENCE FIDELITY: Follow the numbered milestones exactly in the order provided. Do not reorder tiers.
2. HONEST CONFIDENCE CALIBRATION:
   - High Confidence files: Present as foundation facts backed by verified Git history and hard dependency topology.
   - Medium Confidence files: Present as domain-structured inferences (e.g. config before backend, backend before tests). Explicitly acknowledge that domain heuristics guide this ordering.
   - Low Confidence files (Cyclic Clusters): Present as tightly-coupled circular subsystems that must be understood/built as an interconnected unit rather than a strict sequence. NEVER use ordinal language ("first", "then", "next", "step 1", "finally") within a cyclic cluster.
   - Low Confidence files (Unresolved Ties): Acknowledge that these files share identical historical introduction and domain priority.
   - Isolated files: Present separately as orthogonal standalone utilities, configs, or documentation.
3. TEACHING FOCUS: Explain WHY each layer comes when it does, what foundational capabilities it unlocks for the subsequent layers, and what key concepts a developer should master in each step.
4. DO NOT HALLUCINATE: Never invent dependencies or files not present in the input. Ground all claims strictly in the files listed in that milestone.
"""


NarrationLLMCallable = Callable[[str, str], str]  # (system_prompt, user_prompt) -> raw_response_text


class NarrationEngine:
    """Generates pedagogical step-by-step build sequence narratives from Stage C scored ordering results."""

    def generate_narration(
        self,
        scored_result: ScoredOrderingResult,
        refined_result: Optional[RefinedOrderingResult] = None,
        file_contents: Optional[Dict[str, str]] = None,
        llm_provider: Optional[NarrationLLMCallable] = None,
    ) -> SequenceNarrationResult:
        """
        Generates structured build sequence narration using LLM if available,
        or deterministic template engine fallback.
        """
        # 1. Generate the Calibrated Honesty Disclosure
        disclosure = self._build_confidence_disclosure(scored_result, refined_result)

        # 2. Build User Prompt for LLM
        user_prompt = self._build_user_prompt(scored_result, refined_result)

        # 3. If LLM provider supplied, attempt LLM generation
        if llm_provider:
            try:
                raw_response = llm_provider(STAGE_D_SYSTEM_PROMPT, user_prompt)
                # Parse or wrap LLM response into structured result
                return self._parse_or_wrap_llm_response(
                    raw_response=raw_response,
                    scored_result=scored_result,
                    refined_result=refined_result,
                    disclosure=disclosure,
                    prompt_used=user_prompt,
                )
            except Exception as e:
                import traceback
                print(f"\n[LLM PROVIDER EXCEPTION]: {type(e).__name__}: {e}")
                traceback.print_exc()
                pass

        # 4. Deterministic Fallback Generation
        return self._generate_deterministic_narration(
            scored_result=scored_result,
            refined_result=refined_result,
            disclosure=disclosure,
            prompt_used=user_prompt,
        )

    def _build_confidence_disclosure(
        self,
        scored_result: ScoredOrderingResult,
        refined_result: Optional[RefinedOrderingResult] = None,
    ) -> str:
        """Constructs an honest, calibrated explanation of data quality and sequence reliability with reconciliation table."""
        summary = scored_result.repo_confidence_summary
        total_files = len(scored_result.files)
        cyclic_count = len(scored_result.cyclic_files)
        isolated_count = len(scored_result.isolated_files)
        unresolved_tie_count = sum(
            1 for f in scored_result.files
            if f.confidence == "low" and f.path not in scored_result.cyclic_files and f.path not in scored_result.isolated_files
        )

        tier_to_files: Dict[int, List[ScoredFileEntry]] = defaultdict(list)
        for f in scored_result.files:
            tier_to_files[f.tier_index].append(f)

        if not summary.history_available:
            low_parts = []
            if isolated_count > 0:
                low_parts.append(f"{isolated_count} standalone files")
            if cyclic_count > 0:
                low_parts.append(f"{cyclic_count} in circular dependency loops")
            if unresolved_tie_count > 0:
                low_parts.append(f"{unresolved_tie_count} with unclear ordering")
            if len(low_parts) == 1:
                low_desc = low_parts[0]
            elif len(low_parts) == 2:
                low_desc = f"{low_parts[0]} plus {low_parts[1]}"
            elif len(low_parts) > 2:
                low_desc = ", ".join(low_parts[:-1]) + f", plus {low_parts[-1]}"
            else:
                low_desc = "standalone or loosely connected files"

            header = (
                f"**Confidence Calibration Note (No Git History / Zip Upload):**\n"
                f"This repository doesn't have commit history available, so the build order was estimated "
                f"from how files import each other rather than when they were actually written ({summary.medium_pct}% medium confidence). "
                f"About {summary.low_pct}% of files ({low_desc}) don't have a clear position in the sequence, so their placement is an estimate."
            )
        else:
            disclosure_lines = [
                f"**Confidence & Verification Calibration ({total_files} Scored Files):**",
                f"- **Verified History & Clear Structure ({summary.high_pct}% High Confidence):** "
                f"These files have clean acyclic dependencies and were ordered using verified Git commit timestamps (`--follow`).",
            ]

            if summary.medium_pct > 0.0:
                disclosure_lines.append(
                    f"- **Estimated Ordering ({summary.medium_pct}% Medium Confidence):** "
                    f"These files were ordered by domain precedence rules (config $\\rightarrow$ database $\\rightarrow$ core $\\rightarrow$ backend $\\rightarrow$ frontend $\\rightarrow$ examples $\\rightarrow$ tests) "
                    f"to resolve ties where timestamps were identical."
                )
            else:
                disclosure_lines.append(
                    f"- **Estimated Ordering (0.0% Medium Confidence):** "
                    f"No estimation was needed to order these files between different domains, as commit history resolved cross-domain dependencies."
                )

            if cyclic_count > 0:
                disclosure_lines.append(
                    f"- **Cyclic Dependency Clusters ({cyclic_count} Files in Cycles):** "
                    f"These files belong to circular dependency groups (e.g. core framework interdependencies). "
                    f"They are grouped into co-dependent milestones rather than false strict linear sequences."
                )

            if unresolved_tie_count > 0:
                disclosure_lines.append(
                    f"- **Unresolved Sibling Ties ({unresolved_tie_count} Files with Arbitrary Ordering):** "
                    f"These sibling files within the same tier share identical creation dates and domain classifications; "
                    f"with no distinguishing structural or historical signal to order them, their intra-tier sequence is an educated estimate."
                )

            if isolated_count > 0:
                disclosure_lines.append(
                    f"- **Isolated Files ({isolated_count} Standalone Files):** "
                    f"These files have zero internal import links (documentation, configuration scripts, or standalone tools) "
                    f"and can be studied independently."
                )
            header = "\n".join(disclosure_lines)

        # Build reconciliation table
        table_rows = [
            "",
            "**Milestone & Confidence Reconciliation Table:**",
            "| Milestone / Scope | High | Medium | Low | Total Files | Dominant Domain |",
            "| :--- | :---: | :---: | :---: | :---: | :--- |",
        ]

        sorted_tiers = sorted(k for k in tier_to_files.keys() if k >= 0)
        tier_high, tier_med, tier_low = 0, 0, 0

        for step_num, tier_idx in enumerate(sorted_tiers, start=1):
            files = tier_to_files[tier_idx]
            confs = Counter(f.confidence for f in files)
            h, m, l = confs.get("high", 0), confs.get("medium", 0), confs.get("low", 0)
            tier_high += h
            tier_med += m
            tier_low += l
            is_cyclic = any(f.path in scored_result.cyclic_files for f in files)
            cyclic_lbl = " (Cyclic)" if is_cyclic else ""

            # Dominant domain
            dom_counts = Counter()
            for f in files:
                meta = refined_result.node_metadata.get(f.path) if refined_result else None
                dom = meta.domain if meta and meta.domain else None
                if not dom or dom == "uncategorized":
                    p_lower = f.path.lower()
                    if "test" in p_lower:
                        dom = "tests"
                    elif "example" in p_lower or "tutorial" in p_lower or "demo" in p_lower or "sample" in p_lower:
                        dom = "examples"
                    elif "docs" in p_lower:
                        dom = "docs"
                    elif "src/" in p_lower or "app/" in p_lower or "pkg/" in p_lower:
                        dom = "core"
                    else:
                        dom = "core"
                dom_counts[str(dom)] += 1
            top_dom = dom_counts.most_common(1)[0][0] if dom_counts else "core"
            table_rows.append(f"| Milestone {step_num} (Tier {tier_idx}{cyclic_lbl}) | {h} | {m} | {l} | {len(files)} | {top_dom.capitalize()} |")

        iso_files = tier_to_files.get(-1, [])
        iso_h = sum(1 for f in iso_files if f.confidence == "high")
        iso_m = sum(1 for f in iso_files if f.confidence == "medium")
        iso_l = sum(1 for f in iso_files if f.confidence == "low")

        table_rows.append(f"| **Tier Subtotal** | **{tier_high}** | **{tier_med}** | **{tier_low}** | **{len(scored_result.files) - len(iso_files)}** | - |")
        if iso_files:
            table_rows.append(f"| Isolated Files (Tier -1) | {iso_h} | {iso_m} | {iso_l} | {len(iso_files)} | Standalone |")

        tot_h = tier_high + iso_h
        tot_m = tier_med + iso_m
        tot_l = tier_low + iso_l
        table_rows.append(f"| **Total Scored Files** | **{tot_h}** ({summary.high_pct}%) | **{tot_m}** ({summary.medium_pct}%) | **{tot_l}** ({summary.low_pct}%) | **{total_files}** (100%) | - |")

        return header + "\n" + "\n".join(table_rows)

    def _build_user_prompt(
        self,
        scored_result: ScoredOrderingResult,
        refined_result: Optional[RefinedOrderingResult] = None,
    ) -> str:
        """Assembles structured prompt context for LLM narration generation."""
        summary = scored_result.repo_confidence_summary
        total_files = len(scored_result.files)

        # Group scored files by tier
        tier_to_files: Dict[int, List[ScoredFileEntry]] = defaultdict(list)
        for f in scored_result.files:
            tier_to_files[f.tier_index].append(f)

        prompt_lines = [
            f"# REPOSITORY SEQUENCE REASONING DATA",
            f"Total Scored Files: {total_files}",
            f"Confidence Summary: High={summary.high_pct}%, Medium={summary.medium_pct}%, Low={summary.low_pct}%",
            f"History Available: {summary.history_available}",
            f"Total Cyclic Files: {len(scored_result.cyclic_files)}",
            f"Total Isolated Files: {len(scored_result.isolated_files)}",
            "",
            f"## ORDERED TIERS / BUILD MILESTONES:",
        ]

        for tier_idx in sorted(k for k in tier_to_files.keys() if k >= 0):
            files_in_tier = tier_to_files[tier_idx]
            is_cyclic = any(f.path in scored_result.cyclic_files for f in files_in_tier)
            cyclic_tag = " [CYCLIC CLUSTER]" if is_cyclic else ""

            # Domain breakdown
            domain_groups: Dict[str, List[str]] = defaultdict(list)
            for f in files_in_tier:
                meta = refined_result.node_metadata.get(f.path) if refined_result else None
                dom = meta.domain if meta and meta.domain else None
                if not dom or dom == "uncategorized":
                    p_lower = f.path.lower()
                    if "test" in p_lower:
                        dom = "tests"
                    elif "example" in p_lower or "tutorial" in p_lower or "demo" in p_lower or "sample" in p_lower:
                        dom = "examples"
                    elif "docs" in p_lower:
                        dom = "docs"
                    elif p_lower.endswith(".toml") or p_lower.endswith(".yaml") or p_lower.endswith(".json"):
                        dom = "config"
                    elif "src/" in p_lower or "app/" in p_lower or "pkg/" in p_lower:
                        dom = "core"
                    else:
                        dom = "core"
                domain_groups[str(dom)].append(f.path)

            domain_counts = {dom: len(paths) for dom, paths in domain_groups.items()}
            sorted_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)
            top_dom, top_count = sorted_domains[0] if sorted_domains else ("core", len(files_in_tier))
            dom_pct = (top_count / max(len(files_in_tier), 1)) * 100.0

            prompt_lines.append(f"\n### Milestone {tier_idx + 1} (Tier {tier_idx}){cyclic_tag}:")
            prompt_lines.append(f"Dominant Domain: {top_dom} ({top_count}/{len(files_in_tier)} files, {dom_pct:.1f}%)")
            if dom_pct >= 50.0:
                prompt_lines.append(f"Architectural Focus: Primarily {top_dom} ({dom_pct:.0f}% of files in tier).")
            for f in files_in_tier:
                prompt_lines.append(
                    f"  - `{f.path}` | Confidence: {f.confidence.upper()} | Method: {f.tie_break_method or 'none'} | Reason: {f.confidence_reason}"
                )

        if -1 in tier_to_files:
            prompt_lines.append("\n### Isolated Standalone Files (Tier -1):")
            for f in tier_to_files[-1]:
                prompt_lines.append(f"  - `{f.path}` | Confidence: LOW | Reason: {f.confidence_reason}")

        prompt_lines.append("\n## OUTPUT INSTRUCTION & FORMAT REQUIREMENTS:")
        prompt_lines.append("Generate an architectural teaching narrative with the following sections:")
        prompt_lines.append("1. High-Level Architectural Overview (1-2 paragraphs introducing the system)")
        prompt_lines.append("2. For each Milestone above, output a formatted section exactly using this structure:")
        prompt_lines.append("### Milestone <N>: <Pedagogical Title>")
        prompt_lines.append("**Role:** <2-4 sentence architectural explanation. Name 1-2 representative files from this milestone (e.g. `path/to/file.py`) and explain the concrete capabilities or contracts they introduce. Avoid generic filler.>")
        prompt_lines.append("")
        prompt_lines.append("CRITICAL CONSTRAINTS:")
        prompt_lines.append("- For any Milestone marked [CYCLIC CLUSTER], you MUST NOT use ordinal/sequential ordering language (such as 'first', 'second', 'then', 'next', 'finally', or 'step 1') to order files within the cluster. You must explicitly explain that these files form a co-dependent circular subsystem that must be studied and built together as a cohesive unit.")
        prompt_lines.append("- Name specific files from each milestone's file list to explain what they do.")
        prompt_lines.append("- Output valid Markdown.")

        return "\n".join(prompt_lines)

    def _generate_deterministic_narration(
        self,
        scored_result: ScoredOrderingResult,
        refined_result: Optional[RefinedOrderingResult],
        disclosure: str,
        prompt_used: str,
    ) -> SequenceNarrationResult:
        """Generates a high-quality deterministic Markdown sequence narrative without LLM."""
        tier_to_files: Dict[int, List[ScoredFileEntry]] = defaultdict(list)
        for f in scored_result.files:
            tier_to_files[f.tier_index].append(f)

        sorted_tier_indices = sorted(k for k in tier_to_files.keys() if k >= 0)
        total_tiers = len(sorted_tier_indices)

        overview = (
            f"This learning sequence guides you through building and understanding the repository in "
            f"**{total_tiers} logical milestones**, progressing from foundational interfaces with zero internal prerequisites "
            f"to higher-level application components, endpoints, and test suites."
        )

        steps: List[BuildStepNarrative] = []

        for step_num, tier_idx in enumerate(sorted_tier_indices, start=1):
            files_in_tier = tier_to_files[tier_idx]
            file_paths = [f.path for f in files_in_tier]
            is_cyclic = any(f.path in scored_result.cyclic_files for f in files_in_tier)

            # Sub-group files by domain (using node_metadata if available or path heuristics)
            domain_groups: Dict[str, List[str]] = defaultdict(list)
            for f in files_in_tier:
                meta = refined_result.node_metadata.get(f.path) if refined_result else None
                dom = meta.domain if meta and meta.domain else None
                if not dom or dom == "uncategorized":
                    p_lower = f.path.lower()
                    if "test" in p_lower:
                        dom = "tests"
                    elif "example" in p_lower or "tutorial" in p_lower or "demo" in p_lower or "sample" in p_lower:
                        dom = "examples"
                    elif "docs" in p_lower:
                        dom = "docs"
                    elif p_lower.endswith(".toml") or p_lower.endswith(".yaml") or p_lower.endswith(".json"):
                        dom = "config"
                    elif "src/" in p_lower or "app/" in p_lower or "pkg/" in p_lower:
                        dom = "core"
                    else:
                        dom = "core"
                domain_groups[str(dom)].append(f.path)

            # Determine dominant confidence and full confidence breakdown
            conf_counts = Counter(f.confidence for f in files_in_tier)
            dominant_conf = conf_counts.most_common(1)[0][0] if conf_counts else "low"
            conf_breakdown = dict(conf_counts)

            # Determine dominant domain
            domain_counts = {dom: len(paths) for dom, paths in domain_groups.items()}
            sorted_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)
            top_dom, top_count = sorted_domains[0] if sorted_domains else ("core", len(files_in_tier))
            dominant_domain = top_dom if (top_count / max(len(files_in_tier), 1)) >= 0.5 else "mixed"

            # Derive pedagogical title and explanation
            title = self._derive_step_title(tier_idx, total_tiers, files_in_tier, is_cyclic, domain_groups, dominant_domain)
            explanation = self._derive_step_explanation(
                tier_idx, total_tiers, files_in_tier, is_cyclic, domain_groups, dominant_domain
            )

            steps.append(
                BuildStepNarrative(
                    step_number=step_num,
                    title=title,
                    tier_index=tier_idx,
                    files=file_paths,
                    domain_groups=dict(domain_groups),
                    dominant_domain=dominant_domain,
                    is_cyclic_cluster=is_cyclic,
                    dominant_confidence=dominant_conf,
                    confidence_breakdown=conf_breakdown,
                    pedagogical_explanation=explanation,
                    key_symbols_or_concepts=[],
                )
            )

        # Isolated files summary
        isolated_paths = [f.path for f in tier_to_files.get(-1, [])]
        if isolated_paths:
            iso_summary = (
                f"**{len(isolated_paths)} Standalone Files**: "
                f"These files (`{', '.join(isolated_paths[:6])}`{'...' if len(isolated_paths) > 6 else ''}) "
                f"have zero internal dependencies. They represent configuration scripts, documentation assets, or auxiliary tools."
            )
        else:
            iso_summary = "All repository files are integrated into the primary dependency sequence."

        return SequenceNarrationResult(
            overview=overview,
            confidence_disclosure=disclosure,
            steps=steps,
            isolated_files_summary=iso_summary,
            prompt_used=prompt_used,
        )

    def _get_sorted_domain_paths(self, paths: List[str]) -> List[str]:
        """Sorts file paths prioritizing substantive named files over deep __init__.py fixtures."""
        return sorted(paths, key=lambda p: (1 if p.endswith("__init__.py") else 0, len(p.split("/")), p))

    def _select_representative_files(self, domain_groups: Dict[str, List[str]], max_total: int = 4) -> List[str]:
        """Selects representative files per domain, prioritizing substantive named files over deep init fixtures."""
        selected = []
        # Sort domains by size
        sorted_domains = sorted(domain_groups.items(), key=lambda x: len(x[1]), reverse=True)

        for dom, paths in sorted_domains:
            sorted_paths = self._get_sorted_domain_paths(paths)
            for p in sorted_paths:
                if p not in selected:
                    selected.append(p)
                    break
            if len(selected) >= max_total:
                break

        # Fill remaining slots up to max_total
        for dom, paths in sorted_domains:
            sorted_paths = self._get_sorted_domain_paths(paths)
            for p in sorted_paths:
                if p not in selected and len(selected) < max_total:
                    selected.append(p)

        return selected

    def _derive_step_title(
        self,
        tier_idx: int,
        total_tiers: int,
        files: List[ScoredFileEntry],
        is_cyclic: bool,
        domain_groups: Dict[str, List[str]],
        dominant_domain: str,
    ) -> str:
        """Derives a human-friendly pedagogical title for a milestone based on dominant domain and cyclic status."""
        if is_cyclic:
            return f"Core Subsystem Cluster (Tier {tier_idx})"

        if tier_idx == 0:
            return "Foundation Primitives & Base Contracts (Tier 0)"

        if dominant_domain == "tests":
            if len(domain_groups) > 1:
                return f"Test Verification Suites & Subsystem Fixtures (Tier {tier_idx})"
            return f"Test Suite & Verification Layer (Tier {tier_idx})"
        elif dominant_domain in ("core", "backend"):
            if len(domain_groups) > 1:
                return f"Core Framework Extensions & Multi-Domain Modules (Tier {tier_idx})"
            return f"Core Framework Extensions & Handlers (Tier {tier_idx})"
        elif dominant_domain == "examples":
            if len(domain_groups) > 1:
                return f"Application Demos & Example Suites (Tier {tier_idx})"
            return f"Application Demos & Examples (Tier {tier_idx})"
        elif tier_idx == total_tiers - 1:
            return f"Top-Level Composition & Entrypoints (Tier {tier_idx})"
        else:
            return f"Modular Subsystems & Utilities (Tier {tier_idx})"

    def _derive_step_explanation(
        self,
        tier_idx: int,
        total_tiers: int,
        files: List[ScoredFileEntry],
        is_cyclic: bool,
        domain_groups: Dict[str, List[str]],
        dominant_domain: str,
    ) -> str:
        """Derives a pedagogical narrative explaining the architectural role, domain breakdown, and confidence provenance."""
        file_count = len(files)
        representative_files = self._select_representative_files(domain_groups, max_total=4)
        sample_files = ", ".join([f"`{p}`" for p in representative_files])
        if file_count > len(representative_files):
            sample_files += f", and {file_count - len(representative_files)} other files"

        # Tally methods & confidences in this specific tier
        methods = Counter(f.tie_break_method or "none" for f in files)
        confs = Counter(f.confidence for f in files)

        # Build confidence provenance sentence
        prov_parts = []
        if confs.get("high", 0) > 0:
            prov_parts.append(f"{confs['high']}/{file_count} files verified via Git history (`--follow`)")
        if confs.get("medium", 0) > 0:
            prov_parts.append(f"{confs['medium']}/{file_count} ordered using estimated patterns")
        if confs.get("low", 0) > 0:
            if is_cyclic:
                prov_parts.append(f"{confs['low']}/{file_count} co-dependent files in a circular cluster")
            else:
                prov_parts.append(f"{confs['low']}/{file_count} sibling files with unresolved tie-breaks")
        provenance_str = "; ".join(prov_parts)

        # Build domain breakdown text if multiple domains present
        domain_lines = []
        if len(domain_groups) > 1:
            domain_lines.append("**Domain Breakdown:**")
            for dom, dom_files in sorted(domain_groups.items(), key=lambda x: len(x[1]), reverse=True):
                dom_name = dom.capitalize()
                substantive_paths = self._get_sorted_domain_paths(dom_files)
                dom_sample = ", ".join([f"`{p}`" for p in substantive_paths[:3]])
                if len(dom_files) > 3:
                    dom_sample += f" (+{len(dom_files)-3} more)"
                domain_lines.append(f"- **{dom_name} ({len(dom_files)} files):** {dom_sample}")
        domain_section = ("\n" + "\n".join(domain_lines)) if domain_lines else ""

        if tier_idx == 0:
            return (
                f"**Role:** Start by implementing {sample_files}. These {file_count} files have zero internal dependencies "
                f"of their own, serving as independent foundation primitives or self-contained starting points.{domain_section}\n"
                f"**Confidence & Provenance:** {provenance_str}."
            )
        elif is_cyclic:
            return (
                f"**Role:** This milestone comprises {file_count} co-dependent files ({sample_files}) that form a circular dependency cluster. "
                f"In mature architectures, core subsystems (e.g. application context, request routing, and response wrappers) often reference each other. "
                f"These files should be studied together as a cohesive subsystem rather than in a strict linear order.{domain_section}\n"
                f"**Confidence & Provenance:** {provenance_str}."
            )
        elif dominant_domain == "tests":
            tests_count = len(domain_groups.get("tests", []))
            other_count = file_count - tests_count
            if other_count > 0:
                other_doms = [d for d in domain_groups if d != "tests"]
                other_samples_list = []
                for d in sorted(other_doms, key=lambda d: len(domain_groups[d]), reverse=True):
                    sorted_d = self._get_sorted_domain_paths(domain_groups[d])
                    other_samples_list.extend([f"`{p}`" for p in sorted_d[:2]])
                other_samples = ", ".join(other_samples_list)
                role_intro = (
                    f"This milestone is predominantly a test verification layer ({tests_count}/{file_count} files) "
                    f"alongside {other_count} additional module(s) ({other_samples}). These files validate subsystem contracts, "
                    f"integration behaviors, and error handling for features implemented in earlier tiers."
                )
            else:
                role_intro = (
                    f"Implement the test suite files ({sample_files}). These {file_count} files consume the modules built in earlier tiers "
                    f"to validate subsystem contracts, error handling, and behavioral regressions."
                )
            return (
                f"**Role:** {role_intro}{domain_section}\n"
                f"**Confidence & Provenance:** {provenance_str}."
            )
        elif dominant_domain == "examples":
            examples_count = len(domain_groups.get("examples", []))
            other_count = file_count - examples_count
            if other_count > 0:
                other_doms = [d for d in domain_groups if d != "examples"]
                other_samples_list = []
                for d in sorted(other_doms, key=lambda d: len(domain_groups[d]), reverse=True):
                    sorted_d = self._get_sorted_domain_paths(domain_groups[d])
                    other_samples_list.extend([f"`{p}`" for p in sorted_d[:2]])
                other_samples = ", ".join(other_samples_list)
                role_intro = (
                    f"This milestone is predominantly an application examples/tutorials layer ({examples_count}/{file_count} files) "
                    f"alongside {other_count} additional module(s) ({other_samples}). These files demonstrate practical usage patterns, "
                    f"integrations, and sample setups built upon earlier tiers."
                )
            else:
                role_intro = (
                    f"Implement reference application examples ({sample_files}). These {file_count} files demonstrate practical "
                    f"usage patterns and application setups built upon earlier tiers."
                )
            return (
                f"**Role:** {role_intro}{domain_section}\n"
                f"**Confidence & Provenance:** {provenance_str}."
            )
        elif tier_idx == total_tiers - 1:
            return (
                f"**Role:** Finalize the build sequence with {sample_files}. These modules consume the underlying architectural layers to provide "
                f"top-level application composition, CLI commands, or end-to-end integration flows.{domain_section}\n"
                f"**Confidence & Provenance:** {provenance_str}."
            )
        else:
            return (
                f"**Role:** Implement {sample_files}. These {file_count} files build upon the foundational contracts established in previous tiers, "
                f"introducing intermediate utilities, service handlers, and domain components.{domain_section}\n"
                f"**Confidence & Provenance:** {provenance_str}."
            )

    def _parse_or_wrap_llm_response(
        self,
        raw_response: str,
        scored_result: ScoredOrderingResult,
        refined_result: Optional[RefinedOrderingResult],
        disclosure: str,
        prompt_used: str,
    ) -> SequenceNarrationResult:
        """Parses LLM markdown output into structured SequenceNarrationResult schema, extracting per-milestone explanations."""
        # Generate base deterministic steps for fallback ground truth
        fallback = self._generate_deterministic_narration(
            scored_result=scored_result,
            refined_result=refined_result,
            disclosure=disclosure,
            prompt_used=prompt_used,
        )

        if not raw_response or not raw_response.strip():
            return fallback

        # Save raw LLM response to file for audit and scrutiny
        try:
            with open("raw_llm_response.txt", "w", encoding="utf-8") as f:
                f.write(raw_response)
        except Exception:
            pass

        # Parse overview and milestones using flexible header regex
        # Supports: "### Milestone 1: ...", "**Milestone 1: ...**", "Milestone 1: ..."
        overview = fallback.overview
        header_pattern = re.compile(
            r'(?i)(?:^|\n)(?:#{1,4}\s+|\*{1,2})?Milestone\s+(\d+)[:\s\-*]+([^\n]*)'
        )
        matches = list(header_pattern.finditer(raw_response))

        parsed_milestones: Dict[int, Tuple[str, str]] = {}

        if matches:
            first_part = raw_response[:matches[0].start()].strip()
        else:
            first_part = raw_response.strip()

        if first_part:
            cleaned_ov = re.sub(r'^#+\s*', '', first_part).strip()
            if cleaned_ov:
                overview = cleaned_ov

            for i, match in enumerate(matches):
                try:
                    m_num = int(match.group(1))
                    raw_title = match.group(2).strip().rstrip('*').strip()
                    start_pos = match.end()
                    end_pos = matches[i + 1].start() if (i + 1) < len(matches) else len(raw_response)
                    block = raw_response[start_pos:end_pos].strip()

                    # Strip any trailing isolated files section
                    block = re.split(r'(?i)(?:^|\n)(?:#{1,4}\s+|\*{1,2})?Isolated\s+Standalone', block)[0].strip()

                    lines = [line.strip() for line in block.split('\n') if line.strip()]
                    title = raw_title
                    explanation = ""

                    if lines:
                        first_line = lines[0]
                        if not title:
                            if first_line.startswith(":") or first_line.startswith("-"):
                                title = first_line.lstrip(":- ").strip()
                                lines = lines[1:]
                            elif "**Title:**" in first_line or "Title:" in first_line:
                                title = re.sub(r'(?i)\*\*title:\*\*|title:', '', first_line).strip()
                                lines = lines[1:]

                    remaining_text = "\n".join(lines).strip()
                    if remaining_text:
                        explanation = remaining_text

                    if explanation:
                        parsed_milestones[m_num] = (title, explanation)
                except Exception:
                    continue

        # Merge parsed explanations into fallback steps, preserving structural ground truth
        merged_steps: List[BuildStepNarrative] = []
        validation_audit = []
        for step in fallback.steps:
            m_num = step.step_number
            if m_num in parsed_milestones:
                p_title, p_expl = parsed_milestones[m_num]
                new_title = p_title if p_title else step.title

                # Perform post-generation prose validation to prevent cross-milestone file references
                validated_expl, stripped_cnt, used_fallback = self._validate_milestone_prose(
                    explanation=p_expl,
                    milestone_files=step.files,
                    fallback_explanation=step.pedagogical_explanation,
                )

                validation_audit.append({
                    "milestone": m_num,
                    "title": new_title,
                    "raw_explanation": p_expl,
                    "validated_explanation": validated_expl,
                    "stripped_sentence_count": stripped_cnt,
                    "used_fallback": used_fallback,
                })

                formatted_expl = validated_expl
                if not formatted_expl.startswith("**Role:**"):
                    formatted_expl = f"**Role:** {formatted_expl}"

                merged_steps.append(
                    BuildStepNarrative(
                        step_number=step.step_number,
                        title=new_title,
                        tier_index=step.tier_index,
                        files=step.files,
                        domain_groups=step.domain_groups,
                        dominant_domain=step.dominant_domain,
                        is_cyclic_cluster=step.is_cyclic_cluster,
                        dominant_confidence=step.dominant_confidence,
                        confidence_breakdown=step.confidence_breakdown,
                        pedagogical_explanation=formatted_expl,
                        key_symbols_or_concepts=[],
                    )
                )
            else:
                validation_audit.append({
                    "milestone": m_num,
                    "title": step.title,
                    "raw_explanation": None,
                    "validated_explanation": step.pedagogical_explanation,
                    "stripped_sentence_count": 0,
                    "used_fallback": True,
                })
                merged_steps.append(step)

        try:
            with open("validation_audit.json", "w", encoding="utf-8") as f:
                json.dump(validation_audit, f, indent=2)
        except Exception:
            pass

        return SequenceNarrationResult(
            overview=overview,
            confidence_disclosure=disclosure,
            steps=merged_steps,
            isolated_files_summary=fallback.isolated_files_summary,
            prompt_used=prompt_used,
        )

    def _validate_milestone_prose(
        self,
        explanation: str,
        milestone_files: List[str],
        fallback_explanation: str,
    ) -> Tuple[str, int, bool]:
        """
        Validates LLM-generated milestone prose against ground-truth AST milestone membership.
        Detects cross-milestone file references, truncated paths, and non-existent files.
        Strips offending sentences, cleans dangling discourse connectives, and safely
        reverts to deterministic explanation if the explanation is substantially compromised.
        Returns (validated_explanation, stripped_sentence_count, used_fallback).
        """
        milestone_file_set = set(milestone_files)
        code_extensions = (
            ".py", ".ts", ".js", ".jsx", ".tsx", ".rs", ".go", ".java", ".cpp", ".cc", ".c",
            ".h", ".hpp", ".tla", ".sh", ".bash", ".toml", ".yaml", ".yml", ".json", ".md"
        )

        # Robust sentence splitting: prevents splitting on e.g., i.e., vs., or mid-identifier dots
        sentences = [
            s.strip() for s in re.split(
                r'(?<!\be\.g)(?<!\bi\.e)(?<!\bvs)(?<=[.!?])\s+(?=[A-Z0-9`"“])',
                explanation
            ) if s.strip()
        ]
        if not sentences:
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', explanation) if s.strip()]

        cleaned_sentences = []
        stripped_count = 0
        stripped_prior = False

        for sentence in sentences:
            words = re.findall(r'[`\'"]?([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9_-]+)[`\'"]?', sentence)
            has_invalid_file = False
            for raw_w in words:
                w = raw_w.replace('\\', '/').strip('`\'"')
                if any(w.endswith(ext) for ext in code_extensions):
                    # Exact path match in milestone
                    if w in milestone_file_set:
                        continue
                    # Basename match: matches if any file in milestone ends with /w or is w
                    if any(mf.endswith('/' + w) or mf == w for mf in milestone_files):
                        continue
                    # File mention is not in this milestone: flag as cross-milestone hallucination
                    has_invalid_file = True
                    break

            if not has_invalid_file:
                # If an immediate predecessor sentence was stripped, normalize dangling discourse connectives
                if stripped_prior:
                    sanitized = re.sub(
                        r'^(Furthermore|Additionally|Moreover|Consequently|As a result|In addition),\s*',
                        '',
                        sentence,
                        flags=re.IGNORECASE
                    )
                    if sanitized:
                        sentence = sanitized[0].upper() + sanitized[1:]
                    stripped_prior = False
                cleaned_sentences.append(sentence)
            else:
                stripped_count += 1
                stripped_prior = True

        # Fall back if:
        # 1. No sentences survived
        # 2. Strict majority of sentences were stripped
        # 3. Remaining sentences contain fewer than 8 words (inadequate stub)
        total_words = sum(len(s.split()) for s in cleaned_sentences)
        if (
            not cleaned_sentences
            or len(cleaned_sentences) < (len(sentences) + 1) // 2
            or total_words < 8
        ):
            return fallback_explanation, stripped_count, True

        return " ".join(cleaned_sentences), stripped_count, False
