"""Secret detection and redaction module."""

import math
import re
from typing import List, Tuple

# Patterns for explicit secret matching
SECRET_PATTERNS: List[re.Pattern] = [
    # AWS Access Key ID
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # AWS Secret Key pattern
    re.compile(r"(?i)(aws_(?:secret_access_key|secret_key|key)\s*[:=]\s*[\"']?)([A-Za-z0-9/+=]{40})([\"']?)"),
    # Private Key blocks
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    # GitHub Tokens
    re.compile(r"\bghp_[a-zA-Z0-9]{36}\b"),
    re.compile(r"\bgithub_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}\b"),
    # Stripe Secret Keys
    re.compile(r"\bsk_(?:test|live)_[0-9a-zA-Z]{24,}\b"),
    # Generic API Key / Secret assignments in code or .env files
    re.compile(r"(?i)\b(api[_\-]?key|secret|password|access[_\-]?token|bearer[_\-]?token)\b\s*[:=]\s*([\"']?)([a-zA-Z0-9_\-\.]{20,})\2"),
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


class SecretScanner:
    """Scans and redacts credentials and high-entropy secrets from text."""

    def __init__(self, entropy_threshold: float = 4.5, min_token_len: int = 20):
        self.entropy_threshold = entropy_threshold
        self.min_token_len = min_token_len

    def scan_and_redact(self, content: str) -> Tuple[str, int]:
        """
        Scans content for secret patterns and high-entropy strings,
        replacing matches in-place with '[REDACTED]'.
        Returns (redacted_content, total_redactions_count).
        """
        if not content:
            return content, 0

        redaction_count = 0
        redacted_content = content

        # 1. Pattern-based redaction
        for pattern in SECRET_PATTERNS:
            def replacer(match: re.Match) -> str:
                nonlocal redaction_count
                redaction_count += 1
                groups = match.groups()
                if groups:
                    # Replace only the secret value group, preserving assignment & quotes
                    matched_full = match.group(0)
                    for grp in reversed(groups):
                        if grp and len(grp) >= 15 and grp not in {"\"", "'"}:
                            return matched_full.replace(grp, "[REDACTED]")
                return "[REDACTED]"

            redacted_content = pattern.sub(replacer, redacted_content)

        # 2. Entropy-based scanning on quoted string literals & values
        string_pattern = re.compile(r"""(["'`])([^\n"'\\]{20,})\1""")

        def entropy_replacer(match: re.Match) -> str:
            nonlocal redaction_count
            quote = match.group(1)
            val = match.group(2)
            if "[REDACTED]" not in val and calculate_entropy(val) >= self.entropy_threshold:
                redaction_count += 1
                return f"{quote}[REDACTED]{quote}"
            return match.group(0)

        final_content = string_pattern.sub(entropy_replacer, redacted_content)
        return final_content, redaction_count
