"""Automated Database Restore Script (Layer 9 Storage).

Validates SHA-256 integrity of backup archive, decompresses, checks SQLite integrity,
and restores database state to target location.
"""

import argparse
import gzip
import hashlib
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from app.db.session import DATABASE_URL


def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 hex digest for a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def restore_backup(
    backup_archive_path: Path,
    target_db_path: Path,
    verify_checksum: bool = True,
) -> bool:
    """Restores database from compressed backup file with validation."""
    if not backup_archive_path.exists():
        raise FileNotFoundError(f"Backup archive not found: {backup_archive_path}")

    # 1. Checksum validation
    if verify_checksum:
        sha_file = backup_archive_path.parent / f"{backup_archive_path.name}.sha256"
        if sha_file.exists():
            expected_sha = sha_file.read_text(encoding="utf-8").strip().split()[0]
            actual_sha = compute_sha256(backup_archive_path)
            if expected_sha.lower() != actual_sha.lower():
                raise ValueError(
                    f"Checksum mismatch! Expected: {expected_sha}, got: {actual_sha}"
                )
            print("[Restore] SHA-256 checksum verified successfully.")

    # 2. Decompress to staging path
    staging_path = target_db_path.parent / f"staging_restore_{target_db_path.name}"
    staging_path.parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(backup_archive_path, "rb") as f_in, open(staging_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    # 3. SQLite Integrity check
    conn = sqlite3.connect(str(staging_path))
    cursor = conn.cursor()
    cursor.execute("PRAGMA integrity_check;")
    check_result = cursor.fetchone()[0]
    if check_result != "ok":
        conn.close()
        staging_path.unlink(missing_ok=True)
        raise RuntimeError(f"Restored database integrity check failed: {check_result}")

    # Query table stats
    cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table';")
    table_count = cursor.fetchone()[0]
    conn.close()

    # 4. Atomically swap/move into target DB path
    if target_db_path.exists():
        backup_current = target_db_path.parent / f"{target_db_path.name}.pre_restore.bak"
        shutil.copy2(target_db_path, backup_current)

    shutil.move(str(staging_path), str(target_db_path))

    print(f"[Restore] Successfully restored database to: {target_db_path}")
    print(f"[Restore] Tables verified: {table_count}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Database Restore Utility")
    parser.add_argument("--backup-path", required=True, help="Path to .sqlite.gz backup archive")
    parser.add_argument("--target-db", default="storage.db", help="Target database output file")
    parser.add_argument("--no-verify", action="store_true", help="Skip SHA-256 verification")
    args = parser.parse_args()

    restore_backup(
        backup_archive_path=Path(args.backup_path),
        target_db_path=Path(args.target_db),
        verify_checksum=not args.no_verify,
    )
