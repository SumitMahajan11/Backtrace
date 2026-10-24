"""Design rules lint test suite.

Ensures no design violations exist in app/ui/components.py and static/style.css:
1. No font-size under 13px (px values 1-12, or rem values below 0.8125).
2. No text-transform: uppercase.
3. No 'IBM Plex Mono' and no 'Newsreader' (except the .brand-title rule).
4. No legacy tokens: var(--brass), var(--teal), var(--text-primary),
   var(--text-secondary), var(--text-tertiary), var(--hairline), var(--panel).
5. No visible string of 5+ uppercase letters in a row in template text (acronyms allowed).
"""

from pathlib import Path
import re
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
TARGET_FILES = [
    ROOT_DIR / "app" / "ui" / "components.py",
    ROOT_DIR / "static" / "style.css",
]

LEGACY_TOKENS = [
    "var(--brass)",
    "var(--teal)",
    "var(--text-primary)",
    "var(--text-secondary)",
    "var(--text-tertiary)",
    "var(--hairline)",
    "var(--panel)",
]


def _read_target_files():
    data = {}
    for path in TARGET_FILES:
        assert path.exists(), f"Target file missing: {path}"
        data[path] = path.read_text(encoding="utf-8")
    return data


def get_font_size_violations(content: str):
    violations = []
    # Match px values under 13px (0 < px < 13)
    for m in re.finditer(r"font-size:\s*([0-9.]+)\s*px", content, re.IGNORECASE):
        val = float(m.group(1))
        if val < 13.0:
            violations.append(m.group(0))
    # Match rem values under 0.8125rem
    for m in re.finditer(r"font-size:\s*([0-9.]+)\s*rem", content, re.IGNORECASE):
        val = float(m.group(1))
        if val < 0.8125:
            violations.append(m.group(0))
    return violations


def get_uppercase_violations(content: str):
    return re.findall(r"text-transform:\s*uppercase", content, re.IGNORECASE)


ALLOWED_UPPERCASE_ACRONYMS = {
    "API",
    "URL",
    "JSON",
    "CSV",
    "HTML",
    "CSS",
    "GITHUB",
    "README",
    "OAUTH",
    "FASTAPI",
    "SQLITE",
    "PYTHON",
    "SHA256",
    "STDOUT",
    "STDERR",
    "HTTPS",
    "HTTP",
    "UUID",
    "UTC",
    "ISO",
    "AST",
    "DOM",
    "REST",
    "SSR",
    "XSS",
    "CSRF",
    "CORS",
    "WASM",
    "LLM",
    "AI",
    "CI",
    "CD",
    "KPI",
    "CTA",
    "SLA",
    "GDPR",
    "CLI",
    "UI",
    "UX",
}


def get_visible_uppercase_word_violations(content: str):
    """Fails on visible string of 5+ uppercase letters in a row in template text
    (e.g., inside HTML tag body: <tag>TEXT</tag>), allowing common acronyms.
    """
    violations = []
    tag_matches = re.finditer(r"<([a-zA-Z0-9]+)[^>]*>([^<]+)</\1>", content)
    for m in tag_matches:
        seg = m.group(2)
        if "{" in seg or ";" in seg or "var " in seg or "const " in seg:
            continue
        words = re.findall(r"\b([A-Z]{5,})\b", seg)
        for w in words:
            if w not in ALLOWED_UPPERCASE_ACRONYMS:
                violations.append((w, seg.strip()))
    return violations


def get_font_literal_violations(content: str):
    violations = []
    # IBM Plex Mono is never allowed
    for m in re.finditer(r"IBM Plex Mono", content):
        violations.append("IBM Plex Mono")

    # Newsreader is only allowed within .brand-title rule
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        if "Newsreader" in line:
            context = "\n".join(lines[max(0, idx - 5) : idx + 1])
            if ".brand-title" not in context:
                violations.append(f"Newsreader at line {idx + 1}")
    return violations


def get_legacy_token_violations(content: str):
    violations = {}
    for token in LEGACY_TOKENS:
        c = content.count(token)
        if c > 0:
            violations[token] = c
    return violations


def test_no_font_size_under_13px():
    files = _read_target_files()
    total_violations = 0
    details = []
    for path, content in files.items():
        v = get_font_size_violations(content)
        count = len(v)
        total_violations += count
        if count > 0:
            details.append(f"{path.name}: {count} violations ({set(v)})")
    assert total_violations == 0, (
        f"Found {total_violations} font-size < 13px (or < 0.8125rem) violations:\n"
        + "\n".join(details)
    )


def test_no_text_transform_uppercase():
    files = _read_target_files()
    total_violations = 0
    details = []
    for path, content in files.items():
        v = get_uppercase_violations(content)
        count = len(v)
        total_violations += count
        if count > 0:
            details.append(f"{path.name}: {count} uppercase rules")
    assert total_violations == 0, (
        f"Found {total_violations} text-transform: uppercase violations:\n"
        + "\n".join(details)
    )


def test_no_forbidden_font_literals():
    files = _read_target_files()
    total_violations = 0
    details = []
    for path, content in files.items():
        v = get_font_literal_violations(content)
        count = len(v)
        total_violations += count
        if count > 0:
            details.append(f"{path.name}: {count} forbidden font literal occurrences")
    assert total_violations == 0, (
        f"Found {total_violations} forbidden font literal occurrences ('IBM Plex Mono' or non-.brand-title 'Newsreader'):\n"
        + "\n".join(details)
    )


def test_no_legacy_tokens():
    files = _read_target_files()
    total_violations = 0
    details = []
    for path, content in files.items():
        v = get_legacy_token_violations(content)
        count = sum(v.values())
        total_violations += count
        if count > 0:
            details.append(f"{path.name}: {v}")
    assert total_violations == 0, (
        f"Found {total_violations} legacy token violations:\n" + "\n".join(details)
    )


def test_no_visible_uppercase_strings_in_templates():
    files = _read_target_files()
    total_violations = 0
    details = []
    for path, content in files.items():
        v = get_visible_uppercase_word_violations(content)
        count = len(v)
        total_violations += count
        if count > 0:
            details.append(f"{path.name}: {count} violations ({v[:5]})")
    assert total_violations == 0, (
        f"Found {total_violations} visible 5+ uppercase strings in template text:\n"
        + "\n".join(details)
    )


def test_no_tier_numbers_or_fill_the_blanks_in_templates():
    """
    Part E requirement:
    Fail on 'Tier [0-9]' and on 'Fill the [Bb]lanks' in visible template text.
    """
    files = _read_target_files()
    violations = []
    for path, content in files.items():
        if path.suffix != ".py":
            continue
        lines = content.splitlines()
        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith('"""'):
                continue
            if re.search(r"Tier\s+[0-9]", line):
                violations.append(f"{path.name}:{idx}: {stripped}")
            if re.search(r"Fill\s+the\s+[Bb]lanks", line):
                violations.append(f"{path.name}:{idx}: {stripped}")
    assert len(violations) == 0, (
        f"Found {len(violations)} forbidden grading wording occurrences:\n"
        + "\n".join(violations)
    )
