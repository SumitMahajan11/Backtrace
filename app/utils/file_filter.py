"""File tree walk, binary detection, path traversal, and junk filtering utilities."""

import os
from pathlib import Path
from typing import Set

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
