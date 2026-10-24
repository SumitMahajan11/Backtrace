"""Data Access Layer (Repository Pattern) for Analysis Jobs and History."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Union
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.db import AnalysisJobModel, utc_now


class AnalysisJobRepository:
    """Repository handling database operations for user analysis jobs and results."""

    @staticmethod
    def create_job(
        session: Session,
        user_id: int,
        repo_url: str = "",
        github_url: Optional[str] = None,
        repo_name: Optional[str] = None,
        commit_ref: Optional[str] = None,
        resolved_sha: Optional[str] = None,
        subpath: Optional[str] = None,
        status: str = "pending",
        run_id: Optional[str] = None,
        failed_stage: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> AnalysisJobModel:
        """Creates and persists a new analysis job record."""
        target_url = github_url or repo_url
        target_name = repo_name or (target_url.rstrip("/").split("/")[-1] if "/" in target_url else target_url)
        target_run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"

        job = AnalysisJobModel(
            user_id=user_id,
            repo_name=target_name,
            github_url=target_url,
            commit_ref=commit_ref,
            resolved_sha=resolved_sha,
            subpath=subpath,
            run_id=target_run_id,
            status=status,
            failed_stage=failed_stage,
            error_message=error_message,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(job)
        session.flush()

        from app.models.db import UsageEventModel
        stmt = (
            select(UsageEventModel)
            .where(
                UsageEventModel.user_id == user_id,
                UsageEventModel.job_id.is_(None),
                UsageEventModel.event_type == "repo_analysis",
            )
            .order_by(UsageEventModel.created_at.desc(), UsageEventModel.id.desc())
            .limit(1)
        )
        unlinked_event = session.scalar(stmt)
        if unlinked_event:
            unlinked_event.job_id = job.id

        session.commit()
        session.refresh(job)
        return job

    @staticmethod
    def get_job_by_id(session: Session, job_id: Union[int, str]) -> Optional[AnalysisJobModel]:
        """Retrieves an analysis job by primary key ID."""
        try:
            numeric_id = int(job_id)
        except (ValueError, TypeError):
            return None
        stmt = select(AnalysisJobModel).where(AnalysisJobModel.id == numeric_id)
        return session.scalar(stmt)

    @staticmethod
    def get_jobs_for_user(session: Session, user_id: int, limit: int = 50, grouped: bool = False) -> List[AnalysisJobModel]:
        """Retrieves past analysis jobs for a specific user, ordered newest first."""
        if grouped:
            return AnalysisJobRepository.get_grouped_jobs_for_user(session, user_id, limit=limit)
        stmt = (
            select(AnalysisJobModel)
            .where(AnalysisJobModel.user_id == user_id)
            .order_by(AnalysisJobModel.created_at.desc())
            .limit(limit)
        )
        jobs = list(session.scalars(stmt).all())
        for j in jobs:
            if not hasattr(j, "runs"):
                j.runs = 1
        return jobs

    @staticmethod
    def get_grouped_jobs_for_user(session: Session, user_id: int, limit: int = 50) -> List[AnalysisJobModel]:
        """
        Retrieves analysis jobs for a specific user grouped by repository URL.
        Returns the latest run for each repository, with a `runs` attribute indicating
        the total number of analysis runs for that repository URL.
        Ordered newest first.
        """
        subq = (
            select(
                func.max(AnalysisJobModel.id).label("latest_id"),
                func.count(AnalysisJobModel.id).label("runs"),
            )
            .where(AnalysisJobModel.user_id == user_id)
            .group_by(AnalysisJobModel.github_url)
            .subquery()
        )

        stmt = (
            select(AnalysisJobModel, subq.c.runs)
            .join(subq, AnalysisJobModel.id == subq.c.latest_id)
            .order_by(AnalysisJobModel.created_at.desc(), AnalysisJobModel.id.desc())
            .limit(limit)
        )
        results = session.execute(stmt).all()
        grouped_jobs = []
        for job, runs in results:
            job.runs = runs
            grouped_jobs.append(job)
        return grouped_jobs

    @staticmethod
    def get_jobs_grouped_by_repo(session: Session, user_id: int, limit: int = 50) -> List[AnalysisJobModel]:
        """Alias for get_grouped_jobs_for_user."""
        return AnalysisJobRepository.get_grouped_jobs_for_user(session, user_id, limit=limit)

    @staticmethod
    def get_user_jobs(session: Session, user_id: int, limit: int = 50) -> List[AnalysisJobModel]:
        """Alias for get_jobs_for_user."""
        return AnalysisJobRepository.get_jobs_for_user(session, user_id, limit)

    @staticmethod
    def delete_job(session: Session, job_id: int, user_id: Optional[int] = None) -> bool:
        """
        Deletes an analysis job by ID.
        If user_id is provided, verifies that the job belongs to that user.
        Returns True if deleted, False if not found or unauthorized.
        """
        job = AnalysisJobRepository.get_job_by_id(session, job_id)
        if not job:
            return False
        if user_id is not None and job.user_id != user_id:
            return False
        session.delete(job)
        session.commit()
        return True

    @staticmethod
    def find_completed_job(
        session: Session,
        user_id: int,
        github_url: str,
        commit_ref: Optional[str] = None,
        subpath: Optional[str] = None,
        resolved_sha: Optional[str] = None,
    ) -> Optional[AnalysisJobModel]:
        """
        Looks up an existing completed analysis job for the user matching
        repo URL, branch/commit_ref, subpath, and commit SHA.
        """
        clean_url = (github_url or "").strip().rstrip("/")
        stmt = (
            select(AnalysisJobModel)
            .where(
                AnalysisJobModel.user_id == user_id,
                AnalysisJobModel.status.in_(["completed", "complete"]),
            )
        )
        stmt = stmt.where(
            (AnalysisJobModel.github_url == clean_url) |
            (AnalysisJobModel.github_url == f"{clean_url}.git") |
            (AnalysisJobModel.github_url == clean_url.rstrip(".git"))
        )
        if commit_ref:
            stmt = stmt.where(AnalysisJobModel.commit_ref == commit_ref)
        else:
            stmt = stmt.where((AnalysisJobModel.commit_ref == None) | (AnalysisJobModel.commit_ref == ""))

        if subpath:
            stmt = stmt.where(AnalysisJobModel.subpath == subpath)
        else:
            stmt = stmt.where((AnalysisJobModel.subpath == None) | (AnalysisJobModel.subpath == ""))

        if resolved_sha:
            stmt = stmt.where(AnalysisJobModel.resolved_sha == resolved_sha)

        stmt = stmt.order_by(AnalysisJobModel.created_at.desc())
        return session.scalars(stmt).first()

    @staticmethod
    def update_job_status(
        session: Session,
        job_id: Union[int, str],
        status: str,
        error_message: Optional[str] = None,
        report_markdown: Optional[str] = None,
        graph_data: Optional[Dict[str, Any]] = None,
        quiz_data: Optional[Dict[str, Any]] = None,
        execution_time_seconds: Optional[float] = None,
        resolved_sha: Optional[str] = None,
        failed_stage: Optional[str] = None,
    ) -> Optional[AnalysisJobModel]:
        """Updates job status, markdown output, graph, quiz results, resolved SHA, failed stage, and execution duration."""
        job = AnalysisJobRepository.get_job_by_id(session, job_id)
        if job:
            try:
                session.refresh(job)
            except Exception:
                pass
            prev_status = str(job.status or "").lower()
            if prev_status == "cancelled" and str(status or "").lower() != "cancelled":
                # Cancelled status is terminal; do not overwrite with completed or failed, and do not refund again
                return job

            job.status = status
            if resolved_sha is not None:
                job.resolved_sha = resolved_sha
            if failed_stage is not None:
                job.failed_stage = failed_stage
            if error_message is not None:
                job.error_message = error_message
            if report_markdown is not None:
                job.markdown_output = report_markdown
            if graph_data is not None:
                job.graph_output_json = json.dumps(graph_data) if isinstance(graph_data, dict) else str(graph_data)
            if quiz_data is not None:
                job.quiz_output_json = json.dumps(quiz_data) if isinstance(quiz_data, dict) else str(quiz_data)
            if execution_time_seconds is not None:
                job.execution_time_seconds = execution_time_seconds
            job.updated_at = utc_now()

            # Refund quota on transition from pending/running to failed/cancelled in the same transaction
            valid_prev = prev_status in ("pending", "running", "processing", "queued")
            target_status = str(status or "").lower()
            if valid_prev and target_status in ("failed", "cancelled"):
                from app.storage.billing_repository import BillingRepository
                BillingRepository.refund_quota(session, job.user_id, job_id=job.id)

            session.commit()
            session.refresh(job)
        return job

    @staticmethod
    def save_job_result(
        session: Session,
        job_id: Union[int, str],
        markdown_output: str,
        graph_output_json: str,
        quiz_output_json: str,
        execution_time_seconds: float = 0.0,
        resolved_sha: Optional[str] = None,
    ) -> Optional[AnalysisJobModel]:
        """Persists the complete analysis outputs upon successful pipeline completion."""
        job = AnalysisJobRepository.get_job_by_id(session, job_id)
        if job:
            try:
                session.refresh(job)
            except Exception:
                pass
            if str(job.status or "").lower() == "cancelled":
                # Do not overwrite cancelled status
                return job
            job.status = "completed"
            if resolved_sha is not None:
                job.resolved_sha = resolved_sha
            job.markdown_output = markdown_output
            job.graph_output_json = graph_output_json
            job.quiz_output_json = quiz_output_json
            job.execution_time_seconds = execution_time_seconds
            job.updated_at = utc_now()
            session.commit()
            session.refresh(job)
        return job
