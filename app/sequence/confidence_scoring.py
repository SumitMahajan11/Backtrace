"""Confidence Scoring Engine (Layer 6 Stage C)."""

from typing import List, Optional
from app.models.history import CommitHistoryResult
from app.sequence.schema import (
    RefinedOrderingResult,
    RepoConfidenceSummary,
    ScoredFileEntry,
    ScoredOrderingResult,
)


class ConfidenceScoringEngine:
    """Assigns file-level confidence scores/reasons and computes repo-level confidence summary metrics."""

    def compute_confidence_scores(
        self,
        refined_result: RefinedOrderingResult,
        commit_history: Optional[CommitHistoryResult] = None,
    ) -> ScoredOrderingResult:
        """
        Maps Stage A & B ordering methods to explicit confidence levels (high/medium/low)
        and builds a repo-level confidence summary.
        """
        history_available = commit_history.history_available if commit_history else True
        history_confidence = commit_history.history_confidence if commit_history else "high"

        scored_entries: List[ScoredFileEntry] = []

        # 1. Process files in tiers
        for tier in refined_result.tiers:
            for entry in tier.ordered_files:
                conf, reason = self._evaluate_file_confidence(
                    path=entry.path,
                    is_cyclic_cluster=tier.is_cyclic_cluster,
                    tie_break_method=entry.tie_break_method,
                    history_available=history_available,
                    history_confidence=history_confidence,
                    cyclic_files=refined_result.cyclic_files,
                )

                scored_entries.append(
                    ScoredFileEntry(
                        path=entry.path,
                        tier_index=tier.tier_index,
                        confidence=conf,
                        confidence_reason=reason,
                        tie_break_method=entry.tie_break_method,
                        reasoning=entry.reasoning,
                    )
                )

        # 2. Process isolated files (no internal dependency signals)
        for iso_path in refined_result.isolated_files:
            scored_entries.append(
                ScoredFileEntry(
                    path=iso_path,
                    tier_index=-1,
                    confidence="low",
                    confidence_reason="isolated, no internal dependency signal",
                    tie_break_method="none",
                )
            )

        # 3. Compute Repo-Level Confidence Summary Metrics
        total_count = len(scored_entries)
        if total_count == 0:
            high_pct, medium_pct, low_pct = 0.0, 0.0, 0.0
        else:
            high_count = sum(1 for f in scored_entries if f.confidence == "high")
            medium_count = sum(1 for f in scored_entries if f.confidence == "medium")
            low_count = sum(1 for f in scored_entries if f.confidence == "low")

            high_pct = round((high_count / total_count) * 100.0, 2)
            medium_pct = round((medium_count / total_count) * 100.0, 2)
            low_pct = round((low_count / total_count) * 100.0, 2)

        summary = RepoConfidenceSummary(
            high_pct=high_pct,
            medium_pct=medium_pct,
            low_pct=low_pct,
            history_available=history_available,
        )

        return ScoredOrderingResult(
            files=scored_entries,
            repo_confidence_summary=summary,
            isolated_files=list(refined_result.isolated_files),
            cyclic_files=list(refined_result.cyclic_files),
        )

    def _evaluate_file_confidence(
        self,
        path: str,
        is_cyclic_cluster: bool,
        tie_break_method: str,
        history_available: bool,
        history_confidence: str,
        cyclic_files: List[str],
    ) -> tuple[str, str]:
        """Evaluates confidence level ('high', 'medium', 'low') and specific rationale for a file."""
        # Low confidence cases:
        if is_cyclic_cluster or path in cyclic_files:
            return "low", "cyclic cluster (circular dependency)"

        if history_available and history_confidence == "reduced":
            return "low", "reduced history confidence (squashed or rebased commits)"

        if tie_break_method == "unresolved":
            return "low", "unresolved tie within tier"

        # High confidence cases:
        if tie_break_method == "none":
            return "high", "topology (hard dependency fact)"

        if tie_break_method == "history":
            return "high", "topology + verified history"

        # Medium confidence cases:
        if tie_break_method == "heuristic":
            return "medium", "topology + domain heuristic tie-break"

        if tie_break_method == "llm":
            return "medium", "topology + LLM tie-break"

        return "medium", f"topology + {tie_break_method} tie-break"
