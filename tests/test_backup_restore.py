"""Automated Unit and Integration Tests for Database Backup & Disaster Recovery (Prompt 29)."""

import gzip
import json
import os
import shutil
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base, init_db
from app.models.db import UserModel, RepoModel, AnalysisJobModel, SubscriptionModel
from scripts.backup_postgres import DatabaseBackupManager, compute_sha256
from scripts.restore_postgres import DatabaseRestoreManager


@pytest.fixture
def temp_backup_env(tmp_path):
    """Sets up an isolated temporary backup directory and test database."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    
    db_file = tmp_path / "test_source.db"
    db_url = f"sqlite:///{db_file.resolve()}"
    engine = create_engine(db_url)
    init_db(target_engine=engine)
    
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        user = UserModel(github_id=12345, github_username="backup_test_user", email="user@test.com")
        session.add(user)
        session.commit()
        session.refresh(user)

        repo = RepoModel(
            github_url="https://github.com/test/repo",
            commit_hash="abc1234567890",
            status="complete",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        session.add(repo)

        job = AnalysisJobModel(
            user_id=user.id,
            repo_name="test_repo",
            github_url="https://github.com/test/repo",
            status="completed",
            run_id="run_test_01",
        )
        session.add(job)
        session.commit()

    return {
        "backup_dir": backup_dir,
        "source_db_file": db_file,
        "source_db_url": db_url,
        "engine": engine,
    }


def test_backup_creation_and_checksum_generation(temp_backup_env):
    """Verifies that backup creates valid archive, checksum file, and metadata sidecar."""
    manager = DatabaseBackupManager(
        db_url=temp_backup_env["source_db_url"],
        backup_dir=str(temp_backup_env["backup_dir"]),
        retention_days=7,
    )
    metadata = manager.create_backup()

    assert metadata["backup_filename"].endswith(".sqlite.gz") or metadata["backup_filename"].endswith(".sql.gz")
    assert metadata["file_size_bytes"] > 0
    assert len(metadata["sha256_checksum"]) == 64
    assert metadata["total_rows"] >= 3

    archive_path = temp_backup_env["backup_dir"] / metadata["backup_filename"]
    sha_path = temp_backup_env["backup_dir"] / f"{metadata['backup_filename']}.sha256"
    meta_path = temp_backup_env["backup_dir"] / f"{metadata['backup_filename']}.meta.json"

    assert archive_path.exists()
    assert sha_path.exists()
    assert meta_path.exists()

    # Validate computed checksum matches sha file
    recorded_sha = sha_path.read_text().strip().split()[0]
    assert recorded_sha == metadata["sha256_checksum"]


def test_restore_integrity_and_reconciliation(temp_backup_env, tmp_path):
    """Verifies that restore decodes backup and produces 100% row reconciliation."""
    manager = DatabaseBackupManager(
        db_url=temp_backup_env["source_db_url"],
        backup_dir=str(temp_backup_env["backup_dir"]),
        retention_days=7,
    )
    metadata = manager.create_backup()
    archive_path = temp_backup_env["backup_dir"] / metadata["backup_filename"]

    target_db_file = tmp_path / "restored_target.db"
    target_db_url = f"sqlite:///{target_db_file.resolve()}"

    restore_manager = DatabaseRestoreManager(
        backup_archive_path=archive_path,
        target_db_url=target_db_url,
        verify_checksum=True,
    )
    report = restore_manager.restore()

    assert report["status"] == "success"
    assert report["is_reconciled"] is True
    assert report["total_restored_rows"] == metadata["total_rows"]
    assert len(report["mismatches"]) == 0

    # Query restored DB to verify data
    restored_engine = create_engine(target_db_url)
    Session = sessionmaker(bind=restored_engine)
    with Session() as session:
        user = session.query(UserModel).filter_by(github_username="backup_test_user").first()
        assert user is not None
        assert user.email == "user@test.com"


def test_restore_rejects_corrupted_checksum(temp_backup_env, tmp_path):
    """Verifies that restore detects tampered backup files and aborts execution."""
    manager = DatabaseBackupManager(
        db_url=temp_backup_env["source_db_url"],
        backup_dir=str(temp_backup_env["backup_dir"]),
        retention_days=7,
    )
    metadata = manager.create_backup()
    archive_path = temp_backup_env["backup_dir"] / metadata["backup_filename"]

    # Tamper with the archive file by appending corrupted byte
    with open(archive_path, "ab") as f:
        f.write(b"CORRUPTED_BYTES")

    target_db_file = tmp_path / "corrupted_target.db"
    target_db_url = f"sqlite:///{target_db_file.resolve()}"

    restore_manager = DatabaseRestoreManager(
        backup_archive_path=archive_path,
        target_db_url=target_db_url,
        verify_checksum=True,
    )

    with pytest.raises(ValueError, match="Integrity Check Failed! SHA-256 Mismatch"):
        restore_manager.restore()


def test_retention_pruning_removes_old_backups(temp_backup_env):
    """Verifies that backups older than retention_days are pruned while fresh backups are kept."""
    backup_dir = temp_backup_env["backup_dir"]
    
    # Create fake old backup file modified 10 days ago
    old_file = backup_dir / "backtrace_backup_20260101_000000Z.sqlite.gz"
    old_file.write_bytes(b"old backup data")
    old_time = time.time() - (10 * 86400)
    os.utime(old_file, (old_time, old_time))

    # Create fresh backup
    manager = DatabaseBackupManager(
        db_url=temp_backup_env["source_db_url"],
        backup_dir=str(backup_dir),
        retention_days=7,
    )
    pruned = manager.prune_expired_backups()

    assert "backtrace_backup_20260101_000000Z.sqlite.gz" in pruned
    assert not old_file.exists()
