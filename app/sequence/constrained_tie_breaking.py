"""Constrained Tie-Breaking Engine (Layer 6 Stage B)."""

from typing import Callable, Dict, List, Optional, Set, Tuple
from app.models.history import CommitHistoryResult
from app.sequence.schema import (
    BaselineOrderingResult,
    FileOrderEntry,
    NodeMetadata,
    RefinedOrderingResult,
    RefinedTier,
)

DOMAIN_PRIORITY: Dict[str, int] = {
    "config": 1,
    "database": 2,
    "core": 3,
    "backend": 4,
    "frontend": 5,
    "examples": 6,
    "tests": 7,
    "docs": 8,
    "uncategorized": 9,
}

LLMProviderCallable = Callable[
    [List[str], Dict[str, str], Dict[str, NodeMetadata]],
    Tuple[List[str], str],
]


class ConstrainedTieBreakerEngine:
    """Refines Stage A baseline ordering tiers by resolving intra-tier ties using history, heuristics, and LLM."""

    def refine_baseline_order(
        self,
        baseline_result: BaselineOrderingResult,
        commit_history: Optional[CommitHistoryResult] = None,
        file_contents: Optional[Dict[str, str]] = None,
        llm_provider: Optional[LLMProviderCallable] = None,
    ) -> RefinedOrderingResult:
        """
        Refines files within each Stage A tier using a 3-stage tie-breaking cascade:
          1. Reliable Git history timestamps
          2. Domain precedence heuristics
          3. Constrained LLM tie-breaking (with strict cross-tier validation)
          4. Unresolved fallback
        """
        file_contents_map = file_contents or {}
        all_tier_files: Set[str] = set()
        for tier in baseline_result.tiers:
            all_tier_files.update(tier.files)

        refined_tiers: List[RefinedTier] = []

        for tier in baseline_result.tiers:
            ordered_entries = self._refine_single_tier(
                tier_files=tier.files,
                is_cyclic_cluster=tier.is_cyclic_cluster,
                commit_history=commit_history,
                node_metadata=baseline_result.node_metadata,
                file_contents=file_contents_map,
                llm_provider=llm_provider,
                all_tier_files=all_tier_files,
            )

            refined_tiers.append(
                RefinedTier(
                    tier_index=tier.tier_index,
                    ordered_files=ordered_entries,
                    is_cyclic_cluster=tier.is_cyclic_cluster,
                )
            )

        return RefinedOrderingResult(
            tiers=refined_tiers,
            isolated_files=list(baseline_result.isolated_files),
            cyclic_files=list(baseline_result.cyclic_files),
            node_metadata=dict(baseline_result.node_metadata),
        )

    def _refine_single_tier(
        self,
        tier_files: List[str],
        is_cyclic_cluster: bool,
        commit_history: Optional[CommitHistoryResult],
        node_metadata: Dict[str, NodeMetadata],
        file_contents: Dict[str, str],
        llm_provider: Optional[LLMProviderCallable],
        all_tier_files: Set[str],
    ) -> List[FileOrderEntry]:
        """Refines file ordering within a single tier."""
        if not tier_files:
            return []

        if len(tier_files) == 1:
            return [FileOrderEntry(path=tier_files[0], tie_break_method="none")]

        # -------------------------------------------------------------
        # Step 1: History-Based Tie-Breaking with Sub-Bucketing
        # -------------------------------------------------------------
        if (
            commit_history
            and commit_history.history_available
            and commit_history.history_confidence != "reduced"
            and commit_history.file_first_appearance
        ):
            history_entries: List[Tuple[str, str]] = []
            has_full_history = True

            for f in tier_files:
                first_app = commit_history.file_first_appearance.get(f)
                if first_app and first_app.timestamp:
                    history_entries.append((f, first_app.timestamp))
                else:
                    has_full_history = False
                    break

            if has_full_history:
                # Group files by timestamp
                from collections import defaultdict
                ts_to_files: Dict[str, List[str]] = defaultdict(list)
                for f, ts in history_entries:
                    ts_to_files[ts].append(f)

                # If all files share the exact same timestamp (0 distinct historical separation),
                # fall through to heuristics/LLM on the whole tier.
                if len(ts_to_files) > 1:
                    sorted_timestamps = sorted(ts_to_files.keys())
                    result_entries: List[FileOrderEntry] = []

                    for ts in sorted_timestamps:
                        subgroup = ts_to_files[ts]
                        if len(subgroup) == 1:
                            result_entries.append(
                                FileOrderEntry(path=subgroup[0], tie_break_method="history")
                            )
                        else:
                            # Subgroup shares identical timestamp — refine via heuristics/LLM
                            sub_entries = self._refine_subgroup_heuristics_or_llm(
                                subgroup_files=subgroup,
                                node_metadata=node_metadata,
                                file_contents=file_contents,
                                llm_provider=llm_provider,
                                all_tier_files=all_tier_files,
                                tier_files=tier_files,
                            )
                            result_entries.extend(sub_entries)

                    return result_entries

        # -------------------------------------------------------------
        # Step 2: Heuristic-Based Tie-Breaking
        # -------------------------------------------------------------
        return self._refine_subgroup_heuristics_or_llm(
            subgroup_files=tier_files,
            node_metadata=node_metadata,
            file_contents=file_contents,
            llm_provider=llm_provider,
            all_tier_files=all_tier_files,
            tier_files=tier_files,
        )

    def _refine_subgroup_heuristics_or_llm(
        self,
        subgroup_files: List[str],
        node_metadata: Dict[str, NodeMetadata],
        file_contents: Dict[str, str],
        llm_provider: Optional[LLMProviderCallable],
        all_tier_files: Set[str],
        tier_files: List[str],
    ) -> List[FileOrderEntry]:
        """Refines a subgroup of tied files (e.g. sharing identical timestamps) via heuristics or LLM."""
        if len(subgroup_files) == 1:
            return [FileOrderEntry(path=subgroup_files[0], tie_break_method="none")]

        file_priorities: List[Tuple[str, int]] = []
        for f in subgroup_files:
            meta = node_metadata.get(f)
            dom = meta.domain if meta else "uncategorized"
            prio = DOMAIN_PRIORITY.get(str(dom).lower(), 8)
            file_priorities.append((f, prio))

        # Check if files span multiple distinct priority levels
        priorities = [p for _, p in file_priorities]
        distinct_priorities = set(priorities)

        if len(distinct_priorities) > 1:
            file_priorities.sort(key=lambda x: x[1])
            return [
                FileOrderEntry(path=f, tie_break_method="heuristic")
                for f, _ in file_priorities
            ]

        # Step 3 & 4: LLM-Based Tie-Breaking & Unresolved Fallback
        return self._resolve_subgroup(
            group_files=subgroup_files,
            node_metadata=node_metadata,
            file_contents=file_contents,
            llm_provider=llm_provider,
            all_tier_files=all_tier_files,
            tier_files=tier_files,
        )

    def _resolve_subgroup(
        self,
        group_files: List[str],
        node_metadata: Dict[str, NodeMetadata],
        file_contents: Dict[str, str],
        llm_provider: Optional[LLMProviderCallable],
        all_tier_files: Set[str],
        tier_files: List[str],
    ) -> List[FileOrderEntry]:
        """Resolves a subgroup of tied files via LLM with strict validation or falls back to unresolved."""
        if not llm_provider:
            return [
                FileOrderEntry(path=f, tie_break_method="unresolved")
                for f in group_files
            ]

        try:
            proposed_order, reasoning = llm_provider(group_files, file_contents, node_metadata)
        except Exception:
            return [
                FileOrderEntry(path=f, tie_break_method="unresolved")
                for f in group_files
            ]

        # Hard Validation
        if set(proposed_order) != set(group_files) or len(proposed_order) != len(group_files):
            return [
                FileOrderEntry(path=f, tie_break_method="unresolved")
                for f in group_files
            ]

        outside_tier_files = [f for f in proposed_order if f not in set(tier_files)]
        if outside_tier_files:
            return [
                FileOrderEntry(path=f, tie_break_method="unresolved")
                for f in group_files
            ]

        return [
            FileOrderEntry(path=f, tie_break_method="llm", reasoning=reasoning)
            for f in proposed_order
        ]
