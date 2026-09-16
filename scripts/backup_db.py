"""Automated Database Backup Script (Layer 9 Storage).

Creates a timestamped, gzip-compressed snapshot of the database, computes SHA-256
checksum for integrity validation, and stores in target backup directory.
"""

import argparse
import gzip
import hashlib
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.db.session import DATABASE_URL


def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 hex digest for a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def create_backup(
    destination_dir: str = "backups",
    db_url: str = DATABASE_URL,
) -> Path:
    """Creates a timestamped, compressed backup with SHA-256 validation."""
    dest_path = Path(destination_dir)
    dest_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")

    if db_url.startswith("sqlite:///"):
        source_db_path = Path(db_url.replace("sqlite:///", ""))
        if not source_db_path.is_absolute():
            source_db_path = Path.cwd() / source_db_path

        archive_filename = f"reverse_db_{timestamp}.sqlite.gz"
        archive_path = dest_path / archive_filename
        sha_path = dest_path / f"{archive_filename}.sha256"

        # Temporary uncompressed snapshot via SQLite online backup API
        temp_snapshot = dest_path / f"temp_{timestamp}.sqlite"
        if source_db_path.exists():
            src_conn = sqlite3.connect(str(source_db_path))
            dst_conn = sqlite3.connect(str(temp_snapshot))
            with dst_conn:
                src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()
        else:
            # Create fresh empty initialized snapshot
            dst_conn = sqlite3.connect(str(temp_snapshot))
            dst_conn.close()

        # Compress snapshot
        with open(temp_snapshot, "rb") as f_in, gzip.open(archive_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

        # Cleanup temp uncompressed file
        if temp_snapshot.exists():
            temp_snapshot.unlink()

        # Compute and record SHA-256
        checksum = compute_sha256(archive_path)
        sha_path.write_text(f"{checksum}  {archive_filename}\n", encoding="utf-8")

        print(f"[Backup] Successfully generated: {archive_path}")
        print(f"[Backup] Checksum (SHA-256): {checksum}")
        return archive_path

    else:
        raise NotImplementedError(f"Automated backup not implemented for DB scheme: {db_url}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automated DB Backup Utility")
    parser.add_argument("--dest", default="backups", help="Target backup storage directory")
    args = parser.parse_args()
    create_backup(destination_dir=args.dest)
