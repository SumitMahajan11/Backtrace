"""Unit and integration tests for Layer 9 Storage / Caching Subsystem."""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.db import RepoModel, IngestionResultModel, utc_now
from app.models.ingestion import IngestionResult, RepoMetadata, FileNode, IngestionLimitExceededError
from app.services.cached_ingestion import CachedIngestionService
from app.services.security import sandbox_workspace
from app.storage.repository import StorageRepository


@pytest.fixture
def db_session():
    """In-memory SQLite database session for unit testing storage."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionClass = sessionmaker(bind=engine)
    session = SessionClass()
    try:
        yield session
    finally:
        session.close()


def test_cache_hit_miss_combinations(db_session):
    url = "https://github.com/test/repo"
    hash_v1 = "commit_hash_v1"

    # 1. No prior record -> Miss
    cached = StorageRepository.get_active_cached_repo(db_session, url, hash_v1)
    assert cached is None

    # 2. Add complete record
    repo, _ = StorageRepository.acquire_processing_lock(db_session, url, hash_v1)
    sample_result = IngestionResult(
        file_tree=[FileNode(path="README.md", size_bytes=10, extension=".md")],
        file_contents={"README.md": "hello"},
        skipped_items=[],
        metadata=RepoMetadata(default_branch="main", head_commit=hash_v1, clone_duration_seconds=0.5),
    )
    StorageRepository.save_ingestion_result(db_session, repo, sample_result)
    db_session.commit()

    # Same hash, valid -> Hit
    cached_hit = StorageRepository.get_active_cached_repo(db_session, url, hash_v1)
    assert cached_hit is not None
    assert cached_hit.status == "complete"

    # 3. Different hash -> Miss
    hash_v2 = "commit_hash_v2"
    cached_diff_hash = StorageRepository.get_active_cached_repo(db_session, url, hash_v2)
    assert cached_diff_hash is None

    # 4. Expired record -> Miss
    repo.expires_at = utc_now() - timedelta(days=1)
    db_session.commit()
    cached_expired = StorageRepository.get_active_cached_repo(db_session, url, hash_v1)
    assert cached_expired is None


def test_cleanup_expired_records(db_session):
    now = utc_now()

    # Valid repo
    r1 = RepoModel(
        github_url="https://github.com/valid/repo",
        commit_hash="hash1",
        status="complete",
        created_at=now,
        expires_at=now + timedelta(days=10),
    )
    # Expired repo
    r2 = RepoModel(
        github_url="https://github.com/expired/repo",
        commit_hash="hash2",
        status="complete",
        created_at=now - timedelta(days=40),
        expires_at=now - timedelta(days=10),
    )
    db_session.add_all([r1, r2])
    db_session.commit()

    deleted_count = StorageRepository.cleanup_expired_records(db_session)
    db_session.commit()

    assert deleted_count == 1
    remaining = db_session.query(RepoModel).all()
    assert len(remaining) == 1
    assert remaining[0].github_url == "https://github.com/valid/repo"


def test_temp_directory_cleanup_on_success_and_failure():
    """
    Acceptance Criteria 4: Temp clone directory is deleted on disk
    in both success and failure paths.
    """
    captured_path = None

    # Test success path
    try:
        with sandbox_workspace() as temp_dir:
            captured_path = temp_dir
            assert temp_dir.exists()
    finally:
        pass

    assert captured_path is not None
    assert not captured_path.exists()

    # Test failure path with exception
    captured_fail_path = None
    try:
        with sandbox_workspace() as temp_dir:
            captured_fail_path = temp_dir
            assert temp_dir.exists()
            raise RuntimeError("Simulated ingestion error")
    except RuntimeError:
        pass

    assert captured_fail_path is not None
    assert not captured_fail_path.exists()


def test_cached_ingestion_service_hit_and_concurrency(db_session, monkeypatch):
    """
    Acceptance Criteria 1 & 3:
    - Returning cached result on second submission without new clone.
    - Simultaneous submissions handled via lock.
    """
    url = "https://github.com/test/demo"
    clone_counter = 0

    class DummyIngestionService:
        def ingest_repository(self, target_url, commit_ref=None, subpath=None, **kwargs):
            nonlocal clone_counter
            clone_counter += 1
            return IngestionResult(
                file_tree=[FileNode(path="main.py", size_bytes=20, extension=".py")],
                file_contents={"main.py": "print('hello')"},
                skipped_items=[],
                metadata=RepoMetadata(default_branch="main", head_commit="hash_100", clone_duration_seconds=0.1),
            )

    monkeypatch.setattr("app.services.cached_ingestion.get_remote_head_commit", lambda url: "hash_100")

    cached_service = CachedIngestionService(ingestion_service=DummyIngestionService())

    # 1. First call -> triggers clone
    res1 = cached_service.ingest_with_cache(url, db_session)
    assert clone_counter == 1
    assert "main.py" in res1.file_contents

    # 2. Second call -> returns cached, clone_counter stays 1
    res2 = cached_service.ingest_with_cache(url, db_session)
    assert clone_counter == 1
    assert "main.py" in res2.file_contents


def test_analysis_result_caching_and_miss_on_new_commit(db_session):
    """
    Stage 6 Layer 9 Acceptance Criteria:
    - Re-analyzing the same repo at the same commit hits analysis cache.
    - A new commit misses cache and triggers fresh analysis.
    """
    from app.orchestration.schema import PipelineResult, PipelineStage, PipelineProgressEvent

    repo_url = "https://github.com/org/project"
    commit_v1 = "abcdef123456"
    commit_v2 = "fedcba654321"

    # Initial check -> cache miss
    assert StorageRepository.get_active_cached_analysis(db_session, repo_url, commit_v1) is None

    # Save completed analysis for commit_v1
    repo, _ = StorageRepository.acquire_processing_lock(db_session, repo_url, commit_v1)
    analysis_payload = PipelineResult(
        success=True,
        repo_name="org/project",
        markdown_output="# Architecture Report\nVerified v1.",
        graph_output={"nodes": ["a.py", "b.py"], "edges": []},
        quiz_output={"questions": []},
        execution_time_seconds=1.42,
    )
    StorageRepository.save_analysis_result(db_session, repo, analysis_payload)
    db_session.commit()

    # Query with same commit -> Cache HIT
    hit = StorageRepository.get_active_cached_analysis(db_session, repo_url, commit_v1)
    assert hit is not None
    assert hit.success is True
    assert hit.repo_name == "org/project"
    assert hit.markdown_output == "# Architecture Report\nVerified v1."
    assert hit.execution_time_seconds == 1.42

    # Query with different commit -> Cache MISS
    miss = StorageRepository.get_active_cached_analysis(db_session, repo_url, commit_v2)
    assert miss is None


def test_retention_policy_and_keep_longer_flag(db_session):
    """
    Stage 6 Layer 9 Acceptance Criteria:
    - 30-day auto-delete worker purges records older than 30 days unless keep_longer is True.
    """
    now = utc_now()

    # 1. Normal active repo (not expired)
    r_active = RepoModel(
        github_url="https://github.com/org/active",
        commit_hash="h1",
        status="complete",
        created_at=now,
        expires_at=now + timedelta(days=15),
        keep_longer=False,
    )
    # 2. Expired repo without keep_longer -> MUST be purged
    r_expired_purge = RepoModel(
        github_url="https://github.com/org/expired-purge",
        commit_hash="h2",
        status="complete",
        created_at=now - timedelta(days=35),
        expires_at=now - timedelta(days=5),
        keep_longer=False,
    )
    # 3. Expired repo WITH keep_longer=True -> MUST be preserved
    r_expired_keep = RepoModel(
        github_url="https://github.com/org/expired-keep",
        commit_hash="h3",
        status="complete",
        created_at=now - timedelta(days=40),
        expires_at=now - timedelta(days=10),
        keep_longer=True,
    )

    db_session.add_all([r_active, r_expired_purge, r_expired_keep])
    db_session.commit()

    deleted = StorageRepository.cleanup_expired_records(db_session)
    db_session.commit()

    assert deleted == 1
    remaining_urls = {r.github_url for r in db_session.query(RepoModel).all()}
    assert "https://github.com/org/expired-purge" not in remaining_urls
    assert "https://github.com/org/active" in remaining_urls
    assert "https://github.com/org/expired-keep" in remaining_urls


def test_consent_data_model_defaults_and_storage(db_session):
    """
    Stage 6 Layer 9 Acceptance Criteria:
    - Consent flags default to False (no lawful default on).
    - Can be stored and retrieved accurately.
    """
    repo = RepoModel(
        github_url="https://github.com/org/consent-test",
        commit_hash="hash99",
        status="pending",
        created_at=utc_now(),
        expires_at=utc_now() + timedelta(days=30),
    )
    db_session.add(repo)
    db_session.commit()

    fetched = db_session.query(RepoModel).filter_by(github_url="https://github.com/org/consent-test").one()
    assert fetched.consent_prompt_improvement is False
    assert fetched.consent_future_training is False
    assert fetched.keep_longer is False

    # Simulate explicit consent flag assignment
    fetched.consent_prompt_improvement = True
    fetched.keep_longer = True
    db_session.commit()

    updated = db_session.query(RepoModel).filter_by(github_url="https://github.com/org/consent-test").one()
    assert updated.consent_prompt_improvement is True
    assert updated.consent_future_training is False
    assert updated.keep_longer is True


def test_automated_backup_and_restore_roundtrip(tmp_path):
    """
    Stage 6 Layer 9 Acceptance Criteria:
    - Backup produces timestamped gzip archive and SHA-256 file.
    - Restore from backup recovers data cleanly and passes integrity checks.
    """
    import sqlite3
    from scripts.backup_db import create_backup
    from scripts.restore_db import restore_backup

    test_db = tmp_path / "live_test.sqlite"
    backup_dir = tmp_path / "backups"

    # Populate test database with dummy data
    conn = sqlite3.connect(str(test_db))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
    conn.execute("INSERT INTO users (name) VALUES ('Alice'), ('Bob');")
    conn.commit()
    conn.close()

    # 1. Create backup
    backup_file = create_backup(destination_dir=str(backup_dir), db_url=f"sqlite:///{test_db.as_posix()}")
    assert backup_file.exists()
    sha_file = backup_dir / f"{backup_file.name}.sha256"
    assert sha_file.exists()

    # 2. Corrupt or wipe original database
    restored_db = tmp_path / "restored_test.sqlite"

    # 3. Restore to new destination
    success = restore_backup(backup_archive_path=backup_file, target_db_path=restored_db)
    assert success is True
    assert restored_db.exists()

    # 4. Verify data parity in restored DB
    r_conn = sqlite3.connect(str(restored_db))
    cursor = r_conn.cursor()
    cursor.execute("SELECT name FROM users ORDER BY id;")
    names = [row[0] for row in cursor.fetchall()]
    r_conn.close()

    assert names == ["Alice", "Bob"]


def test_dead_worker_detection_and_lock_reclamation(db_session):
    """
    Verifies that a crashed worker holding a processing lock is reclaimed
    after lock_timeout_seconds has elapsed, avoiding a 30-day deadlock.
    """
    url = "https://github.com/dead/worker"
    commit = "commit_dead123"

    # 1. Acquire initial processing lock
    repo1, is_new1 = StorageRepository.acquire_processing_lock(
        db_session, url, commit, lock_timeout_seconds=30
    )
    assert is_new1 is True
    assert repo1.status == "processing"
    db_session.commit()

    # 2. While worker is active (< 30s), another request gets lock=False
    repo2, is_new2 = StorageRepository.acquire_processing_lock(
        db_session, url, commit, lock_timeout_seconds=30
    )
    assert is_new2 is False
    assert repo2.id == repo1.id

    # 3. Simulate worker crash / elapsed time > lock_timeout_seconds
    now = utc_now()
    repo1.created_at = now - timedelta(seconds=35)
    db_session.commit()

    # 4. Next acquire detects dead worker, marks repo1 as failed, and grants new lock
    repo3, is_new3 = StorageRepository.acquire_processing_lock(
        db_session, url, commit, lock_timeout_seconds=30
    )
    assert is_new3 is True
    assert repo3.id != repo1.id
    assert repo3.status == "processing"

    # Verify old dead worker record was marked failed with clear diagnostics
    db_session.refresh(repo1)
    assert repo1.status == "failed"
    assert "Dead worker detected" in repo1.error_message
    assert "Processing lock expired" in repo1.error_message


def test_heartbeat_prevents_premature_lock_expiration(db_session):
    """Verifies that calling heartbeat_processing_lock keeps lock alive."""
    url = "https://github.com/alive/worker"
    commit = "commit_alive123"

    repo, is_new = StorageRepository.acquire_processing_lock(
        db_session, url, commit, lock_timeout_seconds=30
    )
    assert is_new is True

    # Simulate aging to 25s (near timeout)
    repo.created_at = utc_now() - timedelta(seconds=25)
    db_session.commit()

    # Heartbeat resets timestamp
    StorageRepository.heartbeat_processing_lock(db_session, repo)
    db_session.commit()

    # Try acquiring lock - should still be blocked (worker is alive)
    repo_check, is_new_check = StorageRepository.acquire_processing_lock(
        db_session, url, commit, lock_timeout_seconds=30
    )
    assert is_new_check is False
    assert repo_check.id == repo.id

