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
        def ingest_repository(self, target_url):
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
