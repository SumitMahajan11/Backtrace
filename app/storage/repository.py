"""Data Access Layer (Repository Pattern) for Layer 9 Storage."""

import json
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.db import IngestionResultModel, RepoModel, utc_now
from app.models.ingestion import FileNode, IngestionResult, RepoMetadata, SkippedItem

DEFAULT_EXPIRY_DAYS = 30


class StorageRepository:
    """Repository handling database access for cached repo records and ingestion payloads."""

    @staticmethod
    def get_active_cached_repo(
        session: Session, github_url: str, commit_hash: str
    ) -> Optional[RepoModel]:
        """
        Retrieves active (unexpired, status='complete') cached entry for (github_url, commit_hash).
        """
        now = utc_now()
        stmt = (
            select(RepoModel)
            .where(
                RepoModel.github_url == github_url,
                RepoModel.commit_hash == commit_hash,
                RepoModel.status == "complete",
                RepoModel.expires_at > now,
            )
            .order_by(RepoModel.created_at.desc())
        )
        return session.scalar(stmt)

    @staticmethod
    def acquire_processing_lock(
        session: Session, github_url: str, commit_hash: str, ttl_days: int = DEFAULT_EXPIRY_DAYS
    ) -> Tuple[RepoModel, bool]:
        """
        Atomically acquires lock or registers repo record for in-flight processing.
        Returns (repo_model, is_newly_acquired_lock).
        """
        now = utc_now()
        expires_at = now + timedelta(days=ttl_days)

        # Check existing complete or processing entry
        stmt = (
            select(RepoModel)
            .where(
                RepoModel.github_url == github_url,
                RepoModel.commit_hash == commit_hash,
                RepoModel.expires_at > now,
            )
            .order_by(RepoModel.created_at.desc())
        )
        existing = session.scalar(stmt)

        if existing:
            if existing.status in ("complete", "processing"):
                return existing, False

        # Create new processing record
        repo = RepoModel(
            github_url=github_url,
            commit_hash=commit_hash,
            status="processing",
            created_at=now,
            expires_at=expires_at,
        )
        session.add(repo)
        session.flush()
        return repo, True

    @staticmethod
    def save_ingestion_result(
        session: Session,
        repo: RepoModel,
        result: IngestionResult,
    ) -> IngestionResultModel:
        """Saves ingestion result payload and updates repo status to complete."""
        file_tree_json = json.dumps([node.model_dump() for node in result.file_tree])
        file_contents_json = json.dumps(result.file_contents)
        skipped_files_json = json.dumps([item.model_dump() for item in result.skipped_items])

        # Estimate redaction count sum if any
        redaction_count = getattr(result, "redaction_count", 0)
        clone_duration_ms = int(result.metadata.clone_duration_seconds * 1000)

        ingestion_payload = IngestionResultModel(
            repo_id=repo.id,
            file_tree_json=file_tree_json,
            file_contents_json=file_contents_json,
            skipped_files_json=skipped_files_json,
            redaction_count=redaction_count,
            clone_duration_ms=clone_duration_ms,
            created_at=utc_now(),
        )
        session.add(ingestion_payload)
        repo.status = "complete"
        session.flush()
        return ingestion_payload

    @staticmethod
    def mark_repo_failed(session: Session, repo: RepoModel, error_message: str) -> None:
        """Marks repository processing as failed."""
        repo.status = "failed"
        repo.error_message = error_message
        session.flush()

    @staticmethod
    def deserialize_ingestion_result(
        repo: RepoModel, result_model: IngestionResultModel
    ) -> IngestionResult:
        """Converts database records back into Pydantic IngestionResult."""
        tree_raw = json.loads(result_model.file_tree_json)
        contents_raw = json.loads(result_model.file_contents_json)
        skipped_raw = json.loads(result_model.skipped_files_json)

        file_tree = [FileNode(**item) for item in tree_raw]
        skipped_items = [SkippedItem(**item) for item in skipped_raw]

        metadata = RepoMetadata(
            default_branch="main",
            head_commit=repo.commit_hash,
            clone_duration_seconds=round(result_model.clone_duration_ms / 1000.0, 2),
            submodule_urls=[],
        )

        return IngestionResult(
            file_tree=file_tree,
            file_contents=contents_raw,
            skipped_items=skipped_items,
            metadata=metadata,
        )

    @staticmethod
    def cleanup_expired_records(session: Session) -> int:
        """Deletes expired records (expires_at <= utc_now()). Returns count of deleted repos."""
        now = utc_now()
        stmt = select(RepoModel).where(RepoModel.expires_at <= now)
        expired_repos = session.scalars(stmt).all()
        count = len(expired_repos)
        for repo in expired_repos:
            session.delete(repo)
        session.flush()
        return count
