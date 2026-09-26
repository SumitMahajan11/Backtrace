"""Secret detection and redaction module."""

import math
import re
from typing import List, Tuple

# Patterns for explicit secret matching
SECRET_PATTERNS: List[re.Pattern] = [
    # AWS Access Key ID
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # AWS Secret Key pattern
    re.compile(r"(?i)(\baws_(?:secret_access_key|secret_key|key)\b\s*[:=]\s*)([\"']?)([A-Za-z0-9/+=]{40})\2"),
    # Private Key blocks
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    # GitHub Tokens
    re.compile(r"\bghp_[a-zA-Z0-9]{36}\b"),
    re.compile(r"\bgithub_pat_[a-zA-Z0-9_]{20,}\b"),
    # Google & Gemini API Keys (AIza...)
    re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    # Tavily Search API Keys (tvly-...)
    re.compile(r"\btvly-[a-zA-Z0-9]{32,}\b"),
    # Stripe Secret & Webhook Keys (sk_live, sk_test, whsec_...)
    re.compile(r"\b(?:sk_(?:test|live)|whsec)_[0-9a-zA-Z]{24,}\b"),
    # JWT Tokens
    re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b"),
    # Explicit secret variable assignments with quotes (e.g. API_KEY = "...", custom_secret: '...')
    re.compile(r"(?i)(\b[a-zA-Z0-9_]*(?:api[_\-]?key|api[_\-]?secret|secret[_\-]?key|auth[_\-]?token|access[_\-]?token|bearer[_\-]?token|private[_\-]?key|client[_\-]?secret|secret|password|passwd)\b\s*[:=]\s*)([\"'])([a-zA-Z0-9_\-\.]{16,})\2"),
]


def calculate_entropy(text: str) -> float:
    """Calculates Shannon entropy for a given string."""
    if not text:
        return 0.0
    entropy = 0.0
    text_len = len(text)
    char_counts = {}
    for char in text:
        char_counts[char] = char_counts.get(char, 0) + 1
    for count in char_counts.values():
        p = count / text_len
        entropy -= p * math.log2(p)
    return entropy


def is_natural_language_or_prose(text: str) -> bool:
    """Returns True if text appears to be natural language, docstrings, error messages, or CSS classes."""
    if not text:
        return False
    words = [w for w in text.split() if w]
    # If it contains 3 or more space-separated words, it's prose/message/CSS list
    if len(words) >= 3:
        return True
    # If it contains common prose punctuation / sentence indicators
    if any(p in text for p in (" not found", " not available", "Please ", "Error:", "description=", "http://", "https://")):
        return True
    return False


def is_css_or_ua_string(context_str: str, val: str) -> bool:
    """Returns True if string is a CSS class list, User-Agent, or template."""
    lower_ctx = (context_str or "").lower()
    lower_val = (val or "").lower()
    if "classname" in lower_ctx or "class=" in lower_ctx or "class " in lower_ctx or "style=" in lower_ctx:
        return True
    if "user-agent" in lower_ctx or "mozilla/" in lower_val or "webkit/" in lower_val or "compatible;" in lower_val:
        return True
    return False


class SecretScanner:
    """Scans and redacts credentials and high-entropy secrets from text."""

    def __init__(self, entropy_threshold: float = 4.5, min_token_len: int = 20):
        self.entropy_threshold = entropy_threshold
        self.min_token_len = min_token_len

    def scan_and_redact(self, content: str) -> Tuple[str, int]:
        """
        Scans content for secret patterns and high-entropy secret assignments,
        replacing matches in-place with '[REDACTED]'.
        Returns (redacted_content, total_redactions_count).
        """
        if not content:
            return content, 0

        redaction_count = 0
        redacted_content = content

        # 1. Pattern-based explicit rules
        for pattern in SECRET_PATTERNS:
            def replacer(match: re.Match) -> str:
                nonlocal redaction_count
                groups = match.groups()
                matched_full = match.group(0)

                if len(groups) >= 3:
                    prefix, quote, val = groups[0], groups[1], groups[2]
                    if is_natural_language_or_prose(val) or is_css_or_ua_string(prefix, val):
                        return matched_full
                    redaction_count += 1
                    q = quote if quote else '"'
                    return f"{prefix}{q}[REDACTED]{q}"
                elif groups:
                    for grp in reversed(groups):
                        if grp and len(grp) >= 15 and grp not in {"\"", "'"}:
                            if is_natural_language_or_prose(grp) or is_css_or_ua_string(matched_full, grp):
                                return matched_full
                            redaction_count += 1
                            return matched_full.replace(grp, "[REDACTED]")
                redaction_count += 1
                return "[REDACTED]"

            redacted_content = pattern.sub(replacer, redacted_content)

        # 2. Entropy-based scanning strictly restricted to secret-like assignments
        secret_assignment_pattern = re.compile(
            r"""(?i)(\b[a-zA-Z0-9_]*(?:key|secret|token|password|passwd|credential|auth|bearer)[a-zA-Z0-9_]*\s*[:=]\s*)(["'`])([^\n"'`]{16,})\2"""
        )

        def assignment_entropy_replacer(match: re.Match) -> str:
            nonlocal redaction_count
            prefix = match.group(1)
            quote = match.group(2)
            val = match.group(3)

            # Skip if already redacted
            if "[REDACTED]" in val:
                return match.group(0)

            # Skip f-strings, CSS, User-Agent, natural language
            if prefix.strip().lower().startswith("f") or is_natural_language_or_prose(val) or is_css_or_ua_string(prefix, val):
                return match.group(0)

            # Check entropy
            if len(val) >= self.min_token_len and calculate_entropy(val) >= self.entropy_threshold:
                redaction_count += 1
                return f"{prefix}{quote}[REDACTED]{quote}"

            return match.group(0)

        final_content = secret_assignment_pattern.sub(assignment_entropy_replacer, redacted_content)
        return final_content, redaction_count
