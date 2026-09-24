"""File tree walk, binary detection, path traversal, and junk filtering utilities."""

import os
from pathlib import Path
from typing import Optional, Set

# Directories to exclude from ingestion
IGNORED_DIRECTORIES: Set[str] = {
    "node_modules",
    "dist",
    "build",
    ".next",
    "__pycache__",
    "target",
    ".venv",
    "venv",
    "env",
    ".git",
    ".idea",
    ".vscode",
    "coverage",
    ".cache",
    ".pytest_cache",
    "bin",
    "obj",
}

# Known binary extensions blocklist
BINARY_EXTENSIONS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".xz",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".lib", ".bin",
    ".pyc", ".pyo", ".pyd", ".class", ".jar",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".flv", ".mkv",
    ".db", ".sqlite", ".sqlite3",
}

MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1 MB


def is_ignored_directory(dir_name: str) -> bool:
    """Returns True if directory name is in the ignored list."""
    return dir_name.lower() in IGNORED_DIRECTORIES or dir_name.startswith(".git")


def is_binary_file(filepath: Path) -> bool:
    """
    Detects if a file is binary using extension blocklist and null-byte sniffing.
    """
    if filepath.suffix.lower() in BINARY_EXTENSIONS:
        return True

    try:
        with open(filepath, "rb") as f:
            chunk = f.read(1024)
            if b"\x00" in chunk:
                return True
    except OSError:
        # If unreadable, treat as binary/unusable
        return True

    return False


def validate_safe_path(target_path: Path, base_dir: Path) -> bool:
    """
    Validates that target_path resides strictly within base_dir (prevents path traversal).
    """
    try:
        resolved_base = base_dir.resolve(strict=True)
        # Use os.path.abspath / resolve for target
        resolved_target = Path(os.path.abspath(target_path))
        return resolved_base in resolved_target.parents or resolved_target == resolved_base
    except (ValueError, OSError):
        return False


def sanitize_and_validate_subpath(subpath: Optional[str]) -> Optional[str]:
    """
    Sanitizes and strictly validates user-supplied subdirectory path against path traversal,
    null bytes, absolute prefixes, and dangerous characters.
    Returns normalized clean subpath (e.g. 'packages/api') or None.
    Raises ValueError on malicious or invalid patterns.
    """
    if not subpath or not subpath.strip():
        return None

    raw = subpath.strip()

    # 1. Null byte check
    if "\x00" in raw or "\0" in raw:
        raise ValueError("Invalid subdirectory path: Null byte injection detected.")

    # 2. Normalize separators
    norm = raw.replace("\\", "/").strip("/")

    # 3. Path traversal patterns & absolute prefixes
    segments = [s for s in norm.split("/") if s]
    if ".." in segments or any(".." in s for s in segments):
        raise ValueError("Invalid subdirectory path: Directory traversal ('..') is strictly prohibited.")
    if raw.startswith("/") or raw.startswith("\\") or ":" in raw:
        raise ValueError("Invalid subdirectory path: Absolute filesystem paths are prohibited.")

    # 4. Length and segment depth guards
    if len(norm) > 255:
        raise ValueError("Invalid subdirectory path: Path exceeds 255 character limit.")
    if len(segments) > 16:
        raise ValueError("Invalid subdirectory path: Path exceeds maximum directory nesting depth (16).")

    # 5. Segment character validation
    import re
    for seg in segments:
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", seg):
            raise ValueError(f"Invalid subdirectory path: Segment '{seg}' contains illegal characters.")

    return "/".join(segments)


def should_include_relative_path(
    rel_path: str,
    subpath: Optional[str] = None,
    size_bytes: Optional[int] = None,
) -> tuple[bool, Optional[str]]:
    """
    Unified filtering rule used by both preflight check and sandboxed ingestion.
    Returns (True, None) if file should be included, or (False, reason_str) if skipped.
    """
    if not rel_path or rel_path == ".gitmodules":
        return False, "skipped — submodule reference or empty path"

    norm_rel = rel_path.replace("\\", "/").strip("/")

    # 1. Subpath scoping
    if subpath:
        clean_sub = subpath.replace("\\", "/").strip("/")
        if not (norm_rel == clean_sub or norm_rel.startswith(clean_sub + "/")):
            return False, "skipped — outside scoped subdirectory"

    # 2. Ignored directories
    parts = norm_rel.split("/")[:-1]
    for part in parts:
        if is_ignored_directory(part):
            return False, f"skipped — ignored directory '{part}'"

    # 3. Binary extension
    ext = Path(norm_rel).suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return False, "skipped — binary file"

    # 4. File size limit
    if size_bytes is not None and size_bytes > MAX_FILE_SIZE_BYTES:
        return False, f"skipped — file size ({size_bytes} bytes) exceeds 1MB limit"

    return True, None

