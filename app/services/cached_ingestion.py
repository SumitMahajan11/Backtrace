"""Service wrapping repository ingestion with Layer 9 cache & in-flight locking."""

import subprocess
import time
from typing import Optional
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.models.ingestion import IngestionResult, IngestionError
from app.services.ingestion import IngestionService
from app.services.security import build_sandboxed_env
from app.storage.repository import StorageRepository


def get_remote_head_commit(github_url: str, timeout_seconds: float = 10.0) -> str:
    """
    Executes a lightweight `git ls-remote` check to fetch remote HEAD commit hash
    without executing a full repo clone.
    """
    env = build_sandboxed_env()
    cmd = ["git", "-c", "core.hooksPath=", "ls-remote", github_url, "HEAD"]
    try:
        res = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if res.returncode == 0 and res.stdout.strip():
            commit_hash = res.stdout.strip().split()[0]
            return commit_hash
    except Exception:
        pass
    # Return fallback identifier if remote ls-remote fails or in test mode
    return "head_latest"


class CachedIngestionService:
    """Orchestrates cached ingestion, handling cache hits, misses, and in-flight locks."""

    def __init__(self, ingestion_service: Optional[IngestionService] = None):
        self.ingestion_service = ingestion_service or IngestionService()

    def ingest_with_cache(
        self,
        github_url: str,
        session: Session,
        commit_ref: Optional[str] = None,
        subpath: Optional[str] = None,
    ) -> IngestionResult:
        """
        Main entry point for repository ingestion:
        1. Resolves lightweight remote HEAD commit hash.
        2. Returns cached result if available and unexpired.
        3. Manages in-flight processing lock for concurrent requests.
        4. Runs sandboxed ingestion on cache miss and persists result.
        """
        commit_hash = get_remote_head_commit(github_url)

        # 1. Cache hit check
        cached_repo = StorageRepository.get_active_cached_repo(session, github_url, commit_hash)
        if cached_repo and cached_repo.ingestion_result and not subpath:
            return StorageRepository.deserialize_ingestion_result(
                cached_repo, cached_repo.ingestion_result
            )

        # 2. Acquire lock / register record
        repo_record, is_new_lock = StorageRepository.acquire_processing_lock(
            session, github_url, commit_hash
        )

        if not is_new_lock and not subpath:
            # Another request is processing or already finished
            if repo_record.status == "complete" and repo_record.ingestion_result:
                return StorageRepository.deserialize_ingestion_result(
                    repo_record, repo_record.ingestion_result
                )
            elif repo_record.status == "processing":
                # Wait for in-flight processing (polling stub up to 10s)
                for _ in range(20):
                    time.sleep(0.5)
                    session.refresh(repo_record)
                    if repo_record.status == "complete" and repo_record.ingestion_result:
                        return StorageRepository.deserialize_ingestion_result(
                            repo_record, repo_record.ingestion_result
                        )

        # 3. Perform fresh sandboxed ingestion
        try:
            result = self.ingestion_service.ingest_repository(
                github_url, commit_ref=commit_ref, subpath=subpath
            )
            # Update commit_hash from ingested result if accurate
            if result.metadata.head_commit:
                repo_record.commit_hash = result.metadata.head_commit

            if not subpath:
                StorageRepository.save_ingestion_result(session, repo_record, result)
            return result
        except Exception as e:
            StorageRepository.mark_repo_failed(session, repo_record, str(e))
            raise
