"""Confidence Scoring Engine (Layer 6 Stage C)."""

import math
from typing import Any, Dict, List, Optional
from app.models.history import CommitHistoryResult
from app.sequence.schema import (
    RefinedOrderingResult,
    RepoConfidenceSummary,
    ScoredFileEntry,
    ScoredOrderingResult,
)


class ConfidenceSummary(dict):
    """Container for confidence calculation metrics supporting dict and attribute access."""

    def __init__(
        self,
        high_pct: int,
        medium_pct: int,
        low_pct: int,
        overall_score: int,
        high_count: int = 0,
        medium_count: int = 0,
        low_count: int = 0,
        total_files: int = 0,
    ):
        super().__init__(
            high_pct=high_pct,
            medium_pct=medium_pct,
            low_pct=low_pct,
            overall_score=overall_score,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            total_files=total_files,
        )

    @property
    def high_pct(self) -> int:
        return self["high_pct"]

    @property
    def medium_pct(self) -> int:
        return self["medium_pct"]

    @property
    def low_pct(self) -> int:
        return self["low_pct"]

    @property
    def overall_score(self) -> int:
        return self["overall_score"]

    @property
    def high_count(self) -> int:
        return self["high_count"]

    @property
    def medium_count(self) -> int:
        return self["medium_count"]

    @property
    def low_count(self) -> int:
        return self["low_count"]

    @property
    def total_files(self) -> int:
        return self["total_files"]


def confidence_summary(files: List[Any]) -> ConfidenceSummary:
    """Computes distribution percentages and overall confidence score across repository files.

    Formula:
        Given N total files:
        1. Extract confidence rating ('high', 'medium', or 'low') for each file:
           - from string elements ('high', 'medium', 'low'),
           - from objects with a 'confidence' attribute (e.g. ScoredFileEntry, Node),
           - or from dictionaries with a 'confidence' or 'confidence_badge' key.
        2. Tally file counts per rating:
           high_count = count(files where confidence == 'high')
           medium_count = count(files where confidence == 'medium')
           low_count = count(files where confidence == 'low')
        3. If N == 0:
           high_pct = 0, medium_pct = 0, low_pct = 0, overall_score = 0.
        4. If N > 0:
           Calculate exact float percentage shares: (count / N) * 100.0.
           Round each percentage to a whole number (integer) using the Largest Remainder
           Method (Hare-Niemeyer method) such that:
             high_pct + medium_pct + low_pct == 100 (exactly)
        5. Define overall_score = high_pct.

    Args:
        files: List of file objects, dictionaries, or confidence strings.

    Returns:
        ConfidenceSummary containing whole numbers:
            high_pct: Percentage of high-confidence files.
            medium_pct: Percentage of medium-confidence files.
            low_pct: Percentage of low-confidence files.
            overall_score: Defined as high_pct.
            high_count: Count of high-confidence files.
            medium_count: Count of medium-confidence files.
            low_count: Count of low-confidence files.
            total_files: Total files evaluated.
    """
    total = len(files)
    high_count, medium_count, low_count = 0, 0, 0

    for item in files:
        if isinstance(item, str):
            c = item.lower()
        elif isinstance(item, dict):
            c = str(item.get("confidence", item.get("confidence_badge", item.get("dominant_confidence", "high")))).lower()
        else:
            c = str(getattr(item, "confidence", getattr(item, "confidence_badge", getattr(item, "dominant_confidence", "high")))).lower()

        if "high" in c:
            high_count += 1
        elif "medium" in c or "med" in c:
            medium_count += 1
        elif "low" in c:
            low_count += 1
        else:
            high_count += 1

    if total == 0:
        return ConfidenceSummary(
            high_pct=0,
            medium_pct=0,
            low_pct=0,
            overall_score=0,
            high_count=0,
            medium_count=0,
            low_count=0,
            total_files=0,
        )

    exact = [
        (high_count / total) * 100.0,
        (medium_count / total) * 100.0,
        (low_count / total) * 100.0,
    ]
    floors = [int(math.floor(x)) for x in exact]
    remainder = 100 - sum(floors)

    remainders = [(exact[i] - floors[i], i) for i in range(3)]
    remainders.sort(key=lambda x: x[0], reverse=True)

    for i in range(remainder):
        idx = remainders[i][1]
        floors[idx] += 1

    high_pct, medium_pct, low_pct = floors[0], floors[1], floors[2]
    overall_score = high_pct

    return ConfidenceSummary(
        high_pct=high_pct,
        medium_pct=medium_pct,
        low_pct=low_pct,
        overall_score=overall_score,
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
        total_files=total,
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

        # 3. Compute Repo-Level Confidence Summary Metrics using unified confidence_summary
        summary_data = confidence_summary(scored_entries)
        summary = RepoConfidenceSummary(
            high_pct=summary_data.high_pct,
            medium_pct=summary_data.medium_pct,
            low_pct=summary_data.low_pct,
            history_available=history_available,
            high_count=summary_data.high_count,
            medium_count=summary_data.medium_count,
            low_count=summary_data.low_count,
            overall_score=summary_data.overall_score,
            total_files=summary_data.total_files,
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
