"""Data Access Layer (Repository Pattern) for Analysis Jobs and History."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Union
from sqlalchemy import select
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
        status: str = "pending",
        run_id: Optional[str] = None,
    ) -> AnalysisJobModel:
        """Creates and persists a new analysis job record."""
        target_url = github_url or repo_url
        target_name = repo_name or (target_url.rstrip("/").split("/")[-1] if "/" in target_url else target_url)
        target_run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"

        job = AnalysisJobModel(
            user_id=user_id,
            repo_name=target_name,
            github_url=target_url,
            run_id=target_run_id,
            status=status,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(job)
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
    def get_jobs_for_user(session: Session, user_id: int, limit: int = 50) -> List[AnalysisJobModel]:
        """Retrieves past analysis jobs for a specific user, ordered newest first."""
        stmt = (
            select(AnalysisJobModel)
            .where(AnalysisJobModel.user_id == user_id)
            .order_by(AnalysisJobModel.created_at.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())

    @staticmethod
    def get_user_jobs(session: Session, user_id: int, limit: int = 50) -> List[AnalysisJobModel]:
        """Alias for get_jobs_for_user."""
        return AnalysisJobRepository.get_jobs_for_user(session, user_id, limit)

    @staticmethod
    def update_job_status(
        session: Session,
        job_id: Union[int, str],
        status: str,
        error_message: Optional[str] = None,
        report_markdown: Optional[str] = None,
        graph_data: Optional[Dict[str, Any]] = None,
        quiz_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[AnalysisJobModel]:
        """Updates job status, markdown output, graph, and quiz results."""
        job = AnalysisJobRepository.get_job_by_id(session, job_id)
        if job:
            job.status = status
            if error_message is not None:
                job.error_message = error_message
            if report_markdown is not None:
                job.markdown_output = report_markdown
            if graph_data is not None:
                job.graph_output_json = json.dumps(graph_data) if isinstance(graph_data, dict) else str(graph_data)
            if quiz_data is not None:
                job.quiz_output_json = json.dumps(quiz_data) if isinstance(quiz_data, dict) else str(quiz_data)
            job.updated_at = utc_now()
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
    ) -> Optional[AnalysisJobModel]:
        """Persists the complete analysis outputs upon successful pipeline completion."""
        job = AnalysisJobRepository.get_job_by_id(session, job_id)
        if job:
            job.status = "completed"
            job.markdown_output = markdown_output
            job.graph_output_json = graph_output_json
            job.quiz_output_json = quiz_output_json
            job.execution_time_seconds = execution_time_seconds
            job.updated_at = utc_now()
            session.commit()
            session.refresh(job)
        return job
