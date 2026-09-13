"""Filesystem path hardening, depth limits, and secure temp dir creation."""

import os
import tempfile
from pathlib import Path

MAX_DIRECTORY_DEPTH = 20
MAX_FILENAME_LENGTH = 255


class PathHardeningError(ValueError):
    """Raised when path depth or length limits are violated."""
    pass


def validate_path_depth_and_length(
    rel_path: Path,
    max_depth: int = MAX_DIRECTORY_DEPTH,
    max_filename_len: int = MAX_FILENAME_LENGTH,
) -> None:
    """
    Enforces maximum directory nesting depth and maximum filename length limits.
    """
    parts = rel_path.parts
    if len(parts) > max_depth:
        raise PathHardeningError(
            f"Path depth ({len(parts)}) exceeds maximum allowed limit of {max_depth} levels."
        )

    for part in parts:
        if len(part) > max_filename_len:
            raise PathHardeningError(
                f"Filename '{part[:20]}...' length ({len(part)}) exceeds maximum limit of {max_filename_len} characters."
            )


def create_secure_temp_dir(prefix: str = "sandbox_") -> Path:
    """
    Creates a secure, unpredictable temporary directory with strict 0700 permissions.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        os.chmod(temp_dir, 0o700)
    except OSError:
        pass
    return temp_dir
