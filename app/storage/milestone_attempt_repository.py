"""Data Access Layer (Repository Pattern) for Milestone Attempts."""

from __future__ import annotations

from typing import List, Optional, Union
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import MilestoneAttemptModel, utc_now


class MilestoneAttemptRepository:
    """Repository handling database persistence and retrieval for milestone attempts."""

    @staticmethod
    def get_attempt_by_id(session: Session, attempt_id: Union[int, str]) -> Optional[MilestoneAttemptModel]:
        """Retrieves a milestone attempt record by primary key ID."""
        try:
            numeric_id = int(attempt_id)
        except (ValueError, TypeError):
            return None
        stmt = select(MilestoneAttemptModel).where(MilestoneAttemptModel.id == numeric_id)
        return session.scalar(stmt)

    @staticmethod
    def get_attempt(
        session: Session, user_id: int, job_id: int, milestone_tier: int
    ) -> Optional[MilestoneAttemptModel]:
        """Retrieves the milestone attempt for a specific (user_id, job_id, milestone_tier)."""
        stmt = select(MilestoneAttemptModel).where(
            MilestoneAttemptModel.user_id == user_id,
            MilestoneAttemptModel.job_id == job_id,
            MilestoneAttemptModel.milestone_tier == milestone_tier,
        )
        return session.scalar(stmt)

    @staticmethod
    def get_attempts_for_job(
        session: Session, user_id: int, job_id: int
    ) -> List[MilestoneAttemptModel]:
        """Retrieves all milestone attempts for a given user and job ordered by tier."""
        stmt = (
            select(MilestoneAttemptModel)
            .where(
                MilestoneAttemptModel.user_id == user_id,
                MilestoneAttemptModel.job_id == job_id,
            )
            .order_by(MilestoneAttemptModel.milestone_tier.asc())
        )
        return list(session.scalars(stmt).all())

    @staticmethod
    def save_or_update_attempt(
        session: Session,
        user_id: int,
        job_id: int,
        milestone_tier: int,
        submitted_code: str,
        status: str = "attempting",
        hint_level_revealed: Optional[int] = None,
        implementation_revealed: Optional[bool] = None,
        last_run_stdout: Optional[str] = None,
        last_run_stderr: Optional[str] = None,
        last_run_exit_code: Optional[int] = None,
        last_run_at: Optional[datetime] = None,
        grading_method: Optional[str] = None,
        grading_details_json: Optional[str] = None,
    ) -> MilestoneAttemptModel:
        """
        Creates or updates a milestone attempt record, enforcing one row per (user, job, milestone).
        """
        attempt = MilestoneAttemptRepository.get_attempt(
            session=session,
            user_id=user_id,
            job_id=job_id,
            milestone_tier=milestone_tier,
        )
        now = utc_now()
        if attempt is None:
            attempt = MilestoneAttemptModel(
                user_id=user_id,
                job_id=job_id,
                milestone_tier=milestone_tier,
                submitted_code=submitted_code,
                status=status,
                hint_level_revealed=hint_level_revealed if hint_level_revealed is not None else 0,
                implementation_revealed=implementation_revealed if implementation_revealed is not None else False,
                last_run_stdout=last_run_stdout,
                last_run_stderr=last_run_stderr,
                last_run_exit_code=last_run_exit_code,
                last_run_at=last_run_at,
                grading_method=grading_method or "structural_only",
                grading_details_json=grading_details_json,
                created_at=now,
                updated_at=now,
            )
            session.add(attempt)
        else:
            attempt.submitted_code = submitted_code
            attempt.status = status
            if hint_level_revealed is not None:
                attempt.hint_level_revealed = max(attempt.hint_level_revealed, hint_level_revealed)
            if implementation_revealed is not None:
                attempt.implementation_revealed = attempt.implementation_revealed or implementation_revealed
            if last_run_stdout is not None:
                attempt.last_run_stdout = last_run_stdout
            if last_run_stderr is not None:
                attempt.last_run_stderr = last_run_stderr
            if last_run_exit_code is not None:
                attempt.last_run_exit_code = last_run_exit_code
            if last_run_at is not None:
                attempt.last_run_at = last_run_at
            if grading_method is not None:
                attempt.grading_method = grading_method
            if grading_details_json is not None:
                attempt.grading_details_json = grading_details_json
            attempt.updated_at = now

        session.commit()
        session.refresh(attempt)
        return attempt

    @staticmethod
    def record_run_result(
        session: Session,
        user_id: int,
        job_id: int,
        milestone_tier: int,
        submitted_code: str,
        stdout: str,
        stderr: str,
        exit_code: Optional[int],
    ) -> MilestoneAttemptModel:
        """
        Records the real execution result (stdout, stderr, exit_code, last_run_at) on the milestone attempt.
        Distinct from graded Submit fields.
        """
        attempt = MilestoneAttemptRepository.get_attempt(
            session=session,
            user_id=user_id,
            job_id=job_id,
            milestone_tier=milestone_tier,
        )
        now = utc_now()
        if attempt is None:
            attempt = MilestoneAttemptModel(
                user_id=user_id,
                job_id=job_id,
                milestone_tier=milestone_tier,
                submitted_code=submitted_code,
                status="not_started",
                last_run_stdout=stdout,
                last_run_stderr=stderr,
                last_run_exit_code=exit_code,
                last_run_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(attempt)
        else:
            attempt.submitted_code = submitted_code
            attempt.last_run_stdout = stdout
            attempt.last_run_stderr = stderr
            attempt.last_run_exit_code = exit_code
            attempt.last_run_at = now
            # Never touches status or counts as an attempt on Run
            attempt.updated_at = now

        session.commit()
        session.refresh(attempt)
        return attempt
