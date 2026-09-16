"""Data Access Layer (Repository Pattern) for Layer 9 Storage."""

import json
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.db import AnalysisResultModel, IngestionResultModel, RepoModel, utc_now
from app.models.ingestion import FileNode, IngestionResult, RepoMetadata, SkippedItem
from app.orchestration.schema import PipelineResult

DEFAULT_EXPIRY_DAYS = 30


class StorageRepository:
    """Repository handling database access for cached repo records, ingestion payloads, and analysis results."""

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
    def get_active_cached_analysis(
        session: Session, github_url: str, commit_hash: str
    ) -> Optional[PipelineResult]:
        """
        Retrieves active unexpired cached PipelineResult for (github_url, commit_hash).
        Keyed strictly by (repo_url, commit_hash) so new commits always miss cache.
        """
        repo = StorageRepository.get_active_cached_repo(session, github_url, commit_hash)
        if repo and repo.analysis_result:
            return StorageRepository.deserialize_analysis_result(repo.analysis_result)
        return None

    DEFAULT_PROCESSING_LOCK_TIMEOUT_SECONDS: int = 900  # 15 minutes

    @staticmethod
    def heartbeat_processing_lock(session: Session, repo: RepoModel) -> None:
        """Updates repo created_at timestamp to signal active processing and prevent lock timeout."""
        repo.created_at = utc_now()
        session.flush()

    @staticmethod
    def acquire_processing_lock(
        session: Session,
        github_url: str,
        commit_hash: str,
        ttl_days: int = DEFAULT_EXPIRY_DAYS,
        lock_timeout_seconds: int = DEFAULT_PROCESSING_LOCK_TIMEOUT_SECONDS,
    ) -> Tuple[RepoModel, bool]:
        """
        Atomically acquires lock or registers repo record for in-flight processing.
        Includes dead-worker detection: if an existing record has status='processing'
        older than lock_timeout_seconds, it is marked as failed and a new lock is granted.
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
            if existing.status == "complete":
                return existing, False
            if existing.status == "processing":
                lock_age = (now - existing.created_at).total_seconds()
                if lock_age < lock_timeout_seconds:
                    return existing, False
                # Dead worker detected: processing lock expired
                existing.status = "failed"
                existing.error_message = (
                    f"Processing lock expired after {int(lock_age)}s "
                    f"(timeout: {lock_timeout_seconds}s). Dead worker detected; lock reclaimed."
                )
                session.flush()

        # Create new processing record
        repo = RepoModel(
            github_url=github_url,
            commit_hash=commit_hash,
            status="processing",
            created_at=now,
            expires_at=expires_at,
            keep_longer=False,
            consent_prompt_improvement=False,
            consent_future_training=False,
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
    def save_analysis_result(
        session: Session,
        repo: RepoModel,
        pipeline_result: PipelineResult,
    ) -> AnalysisResultModel:
        """Persists full pipeline analysis result payload into Layer 9 storage."""
        payload_json = pipeline_result.model_dump_json()
        analysis_payload = AnalysisResultModel(
            repo_id=repo.id,
            pipeline_result_json=payload_json,
            execution_time_seconds=pipeline_result.execution_time_seconds,
            created_at=utc_now(),
        )
        session.add(analysis_payload)
        repo.status = "complete"
        session.flush()
        return analysis_payload

    @staticmethod
    def deserialize_analysis_result(analysis_model: AnalysisResultModel) -> PipelineResult:
        """Deserializes database record back into Pydantic PipelineResult."""
        return PipelineResult.model_validate_json(analysis_model.pipeline_result_json)

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
        """
        Deletes expired records (expires_at <= utc_now()) UNLESS keep_longer is True.
        Enforces 30-day auto-delete worker policy while respecting user retention opt-in flag.
        Returns count of deleted repos.
        """
        now = utc_now()
        stmt = (
            select(RepoModel)
            .where(
                RepoModel.expires_at <= now,
                RepoModel.keep_longer.is_(False),
            )
        )
        expired_repos = session.scalars(stmt).all()
        count = len(expired_repos)
        for repo in expired_repos:
            session.delete(repo)
        session.flush()
        return count

