"""Curated Milestone Expected Output Registry (Prompt 17 - Tier 2 Grading).

Provides stored, non-invented expected stdout definitions for popular and demo repositories,
as well as extracting dynamic expected output contracts stored in graph_data.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


# Curated repository and milestone expectation registry
CURATED_REGISTRY: Dict[str, Dict[int, Dict[str, Any]]] = {
    # Demo and Test repositories
    "reverse/demo-repo": {
        1: {
            "expected_stdout": "Config loaded: prod.json, records: 3",
            "match_mode": "contains",
            "description": "Standard configuration and data loading initialization summary",
        },
        2: {
            "expected_stdout": "=== DATA TRANSFORM COMPLETE ===\nProcessed items: 3, errors: 0",
            "match_mode": "contains",
            "description": "ETL pipeline transform validation",
        },
    },
    "reverse/test-piston-repo": {
        2: {
            "expected_stdout": "=== DATA TRANSFORM COMPLETE ===\nProcessed items: 3, errors: 0",
            "match_mode": "contains",
            "description": "Piston sandbox integration transform expectation",
        },
    },
    # Popular Python Repositories
    "psf/requests": {
        1: {
            "expected_stdout": "HTTP Adapter initialized: max_retries=3, status=200",
            "match_mode": "contains",
            "description": "Requests session and adapter initialization output",
        },
    },
    "tiangolo/fastapi": {
        1: {
            "expected_stdout": "Application startup: FastAPI 0.100+ ASGI router ready",
            "match_mode": "contains",
            "description": "FastAPI ASGI lifespan and routing table compilation",
        },
    },
    "pallets/flask": {
        1: {
            "expected_stdout": "Flask WSGI app context created: routing rules matched",
            "match_mode": "contains",
            "description": "Flask WSGI request context dispatcher",
        },
    },
}


class CuratedExpectationsRegistry:
    """Registry evaluating whether a curated expected-output contract exists for a milestone."""

    @staticmethod
    def _normalize_repo_key(repo_url: Optional[str], repo_name: Optional[str]) -> Optional[str]:
        """Normalizes GitHub URLs or repo names to owner/repo format."""
        if not repo_url and not repo_name:
            return None

        candidates = [repo_name or "", repo_url or ""]
        for c in candidates:
            if not c:
                continue
            # Strip git prefixes and extensions
            cleaned = re.sub(r"^https?://github\.com/", "", c.strip())
            cleaned = re.sub(r"\.git$", "", cleaned).strip().lower()
            if "/" in cleaned:
                parts = cleaned.split("/")
                return f"{parts[-2]}/{parts[-1]}"
            elif cleaned:
                return cleaned

        return None

    @classmethod
    def get_curated_expected_output(
        cls,
        repo_url: Optional[str] = None,
        repo_name: Optional[str] = None,
        milestone_tier: int = 1,
        milestone_data: Optional[Dict[str, Any]] = None,
        graph_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves the curated expected output definition for a milestone.
        Checks:
        1. Explicit expected_output attached to milestone_data or graph_data.
        2. Curated registry by normalized repository name.
        """
        # 1. Check milestone_data direct declaration
        if milestone_data:
            if "expected_output" in milestone_data and milestone_data["expected_output"]:
                exp = milestone_data["expected_output"]
                if isinstance(exp, str):
                    return {"expected_stdout": exp, "match_mode": "contains", "description": "Milestone expected output contract"}
                elif isinstance(exp, dict):
                    return exp

        # 2. Check graph_data curated_expectations dictionary
        if graph_data and isinstance(graph_data, dict):
            expectations = graph_data.get("curated_expectations", {}) or graph_data.get("expected_outputs", {})
            if str(milestone_tier) in expectations:
                exp = expectations[str(milestone_tier)]
                if isinstance(exp, str):
                    return {"expected_stdout": exp, "match_mode": "contains", "description": f"Tier {milestone_tier} expected output contract"}
                elif isinstance(exp, dict):
                    return exp
            elif milestone_tier in expectations:
                exp = expectations[milestone_tier]
                if isinstance(exp, str):
                    return {"expected_stdout": exp, "match_mode": "contains", "description": f"Tier {milestone_tier} expected output contract"}
                elif isinstance(exp, dict):
                    return exp

        # 3. Check CURATED_REGISTRY
        repo_key = cls._normalize_repo_key(repo_url, repo_name)
        if repo_key and repo_key in CURATED_REGISTRY:
            tier_defs = CURATED_REGISTRY[repo_key]
            if milestone_tier in tier_defs:
                return tier_defs[milestone_tier]

        # Check by repo basename if full owner/repo not matched
        if repo_key and "/" in repo_key:
            base_name = repo_key.split("/")[-1]
            for reg_key, tier_defs in CURATED_REGISTRY.items():
                if reg_key.endswith(f"/{base_name}") or reg_key == base_name:
                    if milestone_tier in tier_defs:
                        return tier_defs[milestone_tier]

        return None
