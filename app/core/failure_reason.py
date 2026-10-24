"""Centralized failure reason classification using word-boundary regular expressions."""

import re
from typing import Optional

ACCESS_ERROR = "We couldn't access this repository (it may be private or the link is wrong)"
LARGE_ERROR = "The repository is too large"
GENERIC_ERROR = "Something went wrong on our side"

# Word-boundary regexes
# 1. "Too large" is checked first (only size / file-count limits)
_LARGE_REGEX = re.compile(
    r"\b(?:too large|large repository|size limit|file limit|file cap|too many files|size boundary|max(?:imum)? files|exceeds? (?:the )?(?:size|file|allowed|maximum|max)|(?:size|file(?:[- ]count)?)\s+(?:exceeds?|limit|cap))\b",
    re.IGNORECASE,
)

# 2. Access issues checked second
_ACCESS_REGEX = re.compile(
    r"\b(?:authentication\s+failed|access\s+denied|could\s+not\s+read\s+username|not\s+publicly\s+reachable)\b|"
    r"repository\s+.*?not\s+found|"
    r"clon(?:e|ing)\s+.*?(?:failed|denied)",
    re.IGNORECASE,
)


def failure_reason(error_message: Optional[str]) -> str:
    """Map raw job error message to one of three clean user-facing sentences."""
    if not error_message:
        return GENERIC_ERROR

    err = str(error_message).strip()
    if not err:
        return GENERIC_ERROR

    # Check "too large" first
    if _LARGE_REGEX.search(err):
        return LARGE_ERROR

    # Check access second
    if _ACCESS_REGEX.search(err):
        return ACCESS_ERROR

    # Generic fallback
    return GENERIC_ERROR


map_failure_reason = failure_reason
