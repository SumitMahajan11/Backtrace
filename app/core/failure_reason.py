"""Centralized failure reason classification using word-boundary regular expressions."""

import re
from typing import Any, Optional

ACCESS_ERROR = "We couldn't access this repository (it may be private or the link is wrong)"
LARGE_ERROR = "The repository is too large"
GENERIC_ERROR = "Something went wrong on our side"
GITHUB_BUSY_ERROR = "GitHub is busy right now. Try again in a few minutes."

# Word-boundary regexes
# 1. "Too large" is checked first (only size / file-count limits)
_LARGE_REGEX = re.compile(
    r"\b(?:too large|large repository|size limit|file limit|file cap|too many files|size boundary|max(?:imum)? files|exceeds? (?:the )?(?:size|file|allowed|maximum|max)|(?:size|file(?:[- ]count)?)\s+(?:exceeds?|limit|cap))\b",
    re.IGNORECASE,
)

# 2. Access issues checked second
_ACCESS_REGEX = re.compile(
    r"\b(?:authentication\s+failed|access\s+denied|could\s+not\s+read\s+username|not\s+publicly\s+reachable)\b|"
    r"repository\s+.*?not\s+found",
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


def map_github_api_error(error: Any, message: Optional[str] = None) -> str:
    """
    Map GitHub API errors to clean user-facing sentences:
    404, 401, or 403 without 'rate limit' -> ACCESS_ERROR
    403 with 'rate limit', or 429 -> GITHUB_BUSY_ERROR ('GitHub is busy right now. Try again in a few minutes.')
    Anything else -> GENERIC_ERROR
    """
    if isinstance(error, int):
        status_code = error
        msg = message or ""
    else:
        status_code = getattr(error, "status_code", None)
        msg = message if message is not None else (str(error) if error is not None else "")

    msg_lower = msg.lower()
    is_rate_limit = "rate limit" in msg_lower

    if status_code in (404, 401):
        return ACCESS_ERROR
    if status_code == 403:
        if is_rate_limit:
            return GITHUB_BUSY_ERROR
        return ACCESS_ERROR
    if status_code == 429:
        return GITHUB_BUSY_ERROR

    return GENERIC_ERROR


github_api_failure_reason = map_github_api_error

