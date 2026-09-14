"""Sequence Narration Engine & Prompt Engineering (Layer 6 Stage D)."""

from collections import Counter, defaultdict
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
   - Low Confidence files (Cyclic Clusters): Present as tightly-coupled circular subsystems that must be understood/built as an interconnected unit rather than a strict sequence.
   - Low Confidence files (Unresolved Ties): Acknowledge that these files share identical historical introduction and domain priority.
   - Isolated files: Present separately as orthogonal standalone utilities, configs, or documentation.
3. TEACHING FOCUS: Explain WHY each layer comes when it does, what foundational capabilities it unlocks for the subsequent layers, and what key concepts a developer should master in each step.
4. DO NOT HALLUCINATE: Never invent dependencies or files not present in the input.
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
                # Attempt to parse or format LLM response, or merge into structured result
                return self._parse_or_wrap_llm_response(
                    raw_response=raw_response,
                    scored_result=scored_result,
                    refined_result=refined_result,
                    disclosure=disclosure,
                    prompt_used=user_prompt,
                )
            except Exception:
                # Fall through to deterministic fallback on error
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

        tier_to_files: Dict[int, List[ScoredFileEntry]] = defaultdict(list)
        for f in scored_result.files:
            tier_to_files[f.tier_index].append(f)

        if not summary.history_available:
            header = (
                f"**Confidence Calibration Note (No Git History / Zip Upload):**\n"
                f"This repository was analyzed without Git commit history. Sequence ordering is derived "
                f"purely from static AST imports and domain-level heuristics ({summary.medium_pct}% medium confidence). "
                f"{summary.low_pct}% of files reside in cyclic clusters or isolated sets where ordering is an educated structural estimate."
            )
        else:
            disclosure_lines = [
                f"**Confidence & Verification Calibration ({total_files} Scored Files):**",
                f"- **Verified History & Hard Topology ({summary.high_pct}% High Confidence):** "
                f"These files have clean acyclic dependencies and were ordered using verified Git commit timestamps (`--follow`).",
            ]

            if summary.medium_pct > 0.0:
                disclosure_lines.append(
                    f"- **Domain Heuristics ({summary.medium_pct}% Medium Confidence):** "
                    f"These files were ordered by domain precedence rules (config $\\rightarrow$ database $\\rightarrow$ core $\\rightarrow$ backend $\\rightarrow$ frontend $\\rightarrow$ examples $\\rightarrow$ tests) "
                    f"to resolve ties where timestamps were identical."
                )
            else:
                disclosure_lines.append(
                    f"- **Domain Heuristics (0.0% Medium Confidence):** "
                    f"Domain heuristics were not needed to break ties between different domains, as commit history resolved cross-domain dependencies."
                )

            if cyclic_count > 0:
                disclosure_lines.append(
                    f"- **Cyclic Dependency Clusters ({cyclic_count} Files in Cycles):** "
                    f"These files belong to circular dependency groups (e.g. core framework interdependencies). "
                    f"They are grouped into co-dependent milestones rather than false strict linear sequences."
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
            prompt_lines.append(f"\n### Milestone {tier_idx + 1} (Tier {tier_idx}){cyclic_tag}:")
            for f in files_in_tier:
                prompt_lines.append(
                    f"  - `{f.path}` | Confidence: {f.confidence.upper()} | Method: {f.tie_break_method or 'none'} | Reason: {f.confidence_reason}"
                )

        if -1 in tier_to_files:
            prompt_lines.append("\n### Isolated Standalone Files (Tier -1):")
            for f in tier_to_files[-1]:
                prompt_lines.append(f"  - `{f.path}` | Confidence: LOW | Reason: {f.confidence_reason}")

        prompt_lines.append("\n## OUTPUT INSTRUCTION:")
        prompt_lines.append("Generate a clear, pedagogical Markdown narration with:")
        prompt_lines.append("1. High-Level Architectural Overview")
        prompt_lines.append("2. Step-by-Step Milestone Breakdown (explaining each tier's role and purpose)")
        prompt_lines.append("3. Standalone Files Summary")

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
                    key_symbols_or_concepts=[f.path for f in files_in_tier[:5]],
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
            prov_parts.append(f"{confs['medium']}/{file_count} ordered via domain precedence heuristics")
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
        """Wraps LLM raw markdown output into the structured SequenceNarrationResult schema."""
        # Generate base deterministic steps
        fallback = self._generate_deterministic_narration(
            scored_result=scored_result,
            refined_result=refined_result,
            disclosure=disclosure,
            prompt_used=prompt_used,
        )

        return SequenceNarrationResult(
            overview=raw_response[:500] if raw_response else fallback.overview,
            confidence_disclosure=disclosure,
            steps=fallback.steps,
            isolated_files_summary=fallback.isolated_files_summary,
            prompt_used=prompt_used,
        )
