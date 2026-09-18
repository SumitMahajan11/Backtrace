"""Points Data Model & Award Engine Service (Prompt 23 & 24).

Handles server-side milestone award computation, complexity floor gating, hint decay multipliers,
anti-race transaction synchronization, derived active point balance calculations with 180-day rolling expiry,
atomic perk redemption (+2 analysis quota for free tier), real badge evaluation, and platform leaderboard.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.db import AnalysisJobModel, MilestoneAttemptModel, PointsLedgerModel, UserModel, utc_now

logger = logging.getLogger("backtrace.points_engine")

# Mutex preventing concurrent double-award or double-redemption race conditions
_points_mutex = threading.Lock()


class PointsRedemptionError(Exception):
    """Exception raised when perk redemption fails business or security validation."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class PointsAwardResult:
    """Encapsulates the server-side point award calculation result."""

    def __init__(
        self,
        points_awarded: int,
        multiplier_applied: float,
        reason: str,
        ledger_entry: Optional[PointsLedgerModel] = None,
    ):
        self.points_awarded = points_awarded
        self.multiplier_applied = multiplier_applied
        self.reason = reason
        self.ledger_entry = ledger_entry

    def to_dict(self) -> Dict[str, Any]:
        return {
            "points_awarded": self.points_awarded,
            "multiplier_applied": self.multiplier_applied,
            "reason": self.reason,
            "ledger_id": self.ledger_entry.id if self.ledger_entry else None,
            "created_at": self.ledger_entry.created_at.isoformat() if self.ledger_entry and self.ledger_entry.created_at else None,
        }


class PointsEngine:
    """Core domain service for points calculation, awards, redemptions, badges, and balance aggregations."""

    @staticmethod
    def extract_repo_complexity(job: AnalysisJobModel) -> Tuple[int, int]:
        """
        Extracts real file and LOC count from job's stored ArchitectureOverview or graph_data.
        Reuses ingested analysis data without recomputing from scratch.
        Returns (total_files, total_loc).
        """
        g_data = job.graph_data if hasattr(job, "graph_data") and job.graph_data else {}
        
        # 1. Check structured ArchitectureOverview dictionary in graph_data
        arch_ov = g_data.get("architecture_overview")
        if isinstance(arch_ov, dict):
            total_files = arch_ov.get("total_files", 0)
            total_loc = arch_ov.get("total_loc", 0)
            if total_files > 0 and total_loc > 0:
                return int(total_files), int(total_loc)

        # 2. Check direct graph_data fields
        total_files = g_data.get("total_files") or g_data.get("total_nodes") or len(g_data.get("nodes", []))
        total_loc = g_data.get("total_loc", 0)

        # 3. If total_loc not in graph_data, estimate/parse from markdown_output or nodes
        if not total_loc and hasattr(job, "markdown_output") and job.markdown_output:
            # Check for Total Analyzed Files in markdown
            f_match = re.search(r"Total Analyzed Files\*\*:\s*`?(\d+)`?", job.markdown_output)
            if f_match and not total_files:
                total_files = int(f_match.group(1))

        # 4. Check node test codes / source code lengths if available
        if not total_loc and g_data.get("nodes"):
            estimated_loc = 0
            for node in g_data.get("nodes", []):
                code = node.get("source_code") or node.get("test_code") or ""
                estimated_loc += len(code.splitlines())
            if estimated_loc > 0:
                total_loc = estimated_loc

        return int(total_files or 0), int(total_loc or 0)

    @staticmethod
    def calculate_award(
        job: AnalysisJobModel,
        attempt: MilestoneAttemptModel,
        is_first_solve: bool,
    ) -> Tuple[int, float, str]:
        """
        Calculates the exact server-side point amount, multiplier, and reason.
        Enforces first-solve rules, complexity floors, and hint penalty decay.
        """
        settings = get_settings()

        # 1. Enforce first solve only
        if settings.POINTS_FIRST_SOLVE_ONLY and not is_first_solve:
            logger.info(
                f"Milestone attempt tier={attempt.milestone_tier} already solved for user={attempt.user_id}, job={job.id}. 0 points awarded."
            )
            return 0, 0.0, "first_solve_already_awarded"

        # 2. Enforce complexity floor
        total_files, total_loc = PointsEngine.extract_repo_complexity(job)
        if total_files < settings.POINTS_MIN_REPO_FILES or total_loc < settings.POINTS_MIN_REPO_LOC:
            logger.info(
                f"Job {job.id} below complexity floor (files={total_files}/{settings.POINTS_MIN_REPO_FILES}, loc={total_loc}/{settings.POINTS_MIN_REPO_LOC}). 0 points awarded."
            )
            return 0, 0.0, "below_complexity_floor"

        # 3. Solution revealed short-circuits straight to 0
        if getattr(attempt, "implementation_revealed", False):
            logger.info(f"Solution revealed for user={attempt.user_id}, job={job.id}, tier={attempt.milestone_tier}. 0 points awarded.")
            return 0, settings.POINTS_SOLUTION_REVEALED_MULTIPLIER, "solution_revealed"

        # 4. Apply progressive hint multipliers
        hint_level = getattr(attempt, "hint_level_revealed", 0) or 0
        if hint_level == 1:
            multiplier = settings.POINTS_HINT_1_MULTIPLIER
            points = int(settings.POINTS_BASE_VALUE * multiplier)
            return points, multiplier, "milestone_solved_hint_1"
        elif hint_level >= 2:
            multiplier = settings.POINTS_HINT_2_MULTIPLIER
            points = int(settings.POINTS_BASE_VALUE * multiplier)
            return points, multiplier, "milestone_solved_hint_2"
        else:
            multiplier = 1.0
            points = int(settings.POINTS_BASE_VALUE)
            return points, multiplier, "milestone_solved_no_hints"

    @staticmethod
    def award_points_for_milestone(
        session: Session,
        user_id: int,
        job: AnalysisJobModel,
        milestone_tier: int,
        attempt: MilestoneAttemptModel,
    ) -> PointsAwardResult:
        """
        Awards points upon milestone passing verification.
        Uses database transaction synchronization to prevent concurrent double-awarding.
        Appends immutable record to PointsLedgerModel.
        """
        settings = get_settings()

        with _points_mutex:
            # 1. Acquire DB row-level lock on user row if engine supports it (e.g. Postgres)
            bind = session.get_bind()
            if bind and bind.dialect.name == "postgresql":
                session.scalars(select(UserModel.id).where(UserModel.id == user_id).with_for_update()).first()

            # Check existing ledger records for (user_id, job_id, milestone_tier)
            stmt = (
                select(PointsLedgerModel)
                .where(
                    PointsLedgerModel.user_id == user_id,
                    PointsLedgerModel.job_id == job.id,
                    PointsLedgerModel.milestone_tier == milestone_tier,
                )
            )
            existing_entries = list(session.scalars(stmt).all())
            has_prior_positive_award = any(e.points_awarded > 0 for e in existing_entries)
            is_first_solve = not has_prior_positive_award

            points, multiplier, reason = PointsEngine.calculate_award(
                job=job,
                attempt=attempt,
                is_first_solve=is_first_solve,
            )

            # Insert immutable audit ledger record
            ledger_entry = PointsLedgerModel(
                user_id=user_id,
                job_id=job.id,
                milestone_tier=milestone_tier,
                points_awarded=points,
                multiplier_applied=multiplier,
                reason=reason,
                created_at=utc_now(),
            )
            session.add(ledger_entry)
            session.commit()
            session.refresh(ledger_entry)

            logger.info(
                f"[Points Awarded] user_id={user_id}, job_id={job.id}, tier={milestone_tier}, "
                f"points={points}, multiplier={multiplier}, reason='{reason}', ledger_id={ledger_entry.id}"
            )

            return PointsAwardResult(
                points_awarded=points,
                multiplier_applied=multiplier,
                reason=reason,
                ledger_entry=ledger_entry,
            )

    @staticmethod
    def get_user_points_balance(session: Session, user_id: int) -> int:
        """
        Derived query calculating active, unexpired point balance.
        Points expire after POINTS_EXPIRY_DAYS (default 180 days).
        Redemptions (negative points) deduct from balance.
        Ledger rows are never deleted (pure append-only audit trail).
        """
        settings = get_settings()
        cutoff_date = utc_now() - timedelta(days=settings.POINTS_EXPIRY_DAYS)

        stmt = (
            select(func.coalesce(func.sum(PointsLedgerModel.points_awarded), 0))
            .where(
                PointsLedgerModel.user_id == user_id,
                (PointsLedgerModel.created_at >= cutoff_date) | (PointsLedgerModel.points_awarded < 0),
            )
        )
        balance = session.scalar(stmt)
        return max(0, int(balance or 0))

    @staticmethod
    def get_user_lifetime_points(session: Session, user_id: int) -> int:
        """Calculates total lifetime points earned (excluding redemptions) regardless of expiration."""
        stmt = (
            select(func.coalesce(func.sum(PointsLedgerModel.points_awarded), 0))
            .where(
                PointsLedgerModel.user_id == user_id,
                PointsLedgerModel.points_awarded > 0,
            )
        )
        total = session.scalar(stmt)
        return int(total or 0)

    @staticmethod
    def get_user_expired_points(session: Session, user_id: int) -> int:
        """Calculates total points that have expired past POINTS_EXPIRY_DAYS."""
        settings = get_settings()
        cutoff_date = utc_now() - timedelta(days=settings.POINTS_EXPIRY_DAYS)

        stmt = (
            select(func.coalesce(func.sum(PointsLedgerModel.points_awarded), 0))
            .where(
                PointsLedgerModel.user_id == user_id,
                PointsLedgerModel.created_at < cutoff_date,
                PointsLedgerModel.points_awarded > 0,
            )
        )
        expired = session.scalar(stmt)
        return int(expired or 0)

    @staticmethod
    def get_user_monthly_quota_bonus(session: Session, user_id: int) -> int:
        """
        Calculates total bonus analysis quota redeemed for the current calendar month.
        Each 'redemption_quota_bump_2' entry grants +2 analysis slots.
        """
        settings = get_settings()
        now = utc_now()
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        stmt = (
            select(func.count(PointsLedgerModel.id))
            .where(
                PointsLedgerModel.user_id == user_id,
                PointsLedgerModel.reason.startswith("redemption_quota_bump"),
                PointsLedgerModel.created_at >= start_of_month,
            )
        )
        redemption_count = session.scalar(stmt) or 0
        return int(redemption_count) * settings.POINTS_QUOTA_REWARD_AMOUNT

    @staticmethod
    def redeem_quota_perk(session: Session, user: UserModel) -> Dict[str, Any]:
        """
        Atomically redeems points for +2 repository analysis quota in the current month.
        Enforces:
        - Free tier only (Pro/Paid users have unlimited and receive an explicit 400).
        - Sufficient balance check.
        - Appends negative PointsLedgerModel entry in an atomic transaction.
        """
        settings = get_settings()
        cost = settings.POINTS_QUOTA_REWARD_COST
        amount = settings.POINTS_QUOTA_REWARD_AMOUNT

        # 1. Pro / Paid Tier check
        from app.services.billing_service import BillingService
        billing_status = BillingService.get_user_billing_status(user, session)
        if billing_status.get("tier") == "paid":
            raise PointsRedemptionError(
                "You are already on Backtrace Pro with unlimited repository analyses. Extra quota redemption is not needed.",
                status_code=400,
            )

        with _points_mutex:
            # 2. Acquire DB row-level lock on user row if engine supports it (e.g. Postgres)
            bind = session.get_bind()
            if bind and bind.dialect.name == "postgresql":
                session.scalars(select(UserModel.id).where(UserModel.id == user.id).with_for_update()).first()

            # Server-side balance verification
            current_balance = PointsEngine.get_user_points_balance(session, user.id)
            if current_balance < cost:
                raise PointsRedemptionError(
                    f"Insufficient point balance. You have {current_balance} points, but this perk requires {cost} points.",
                    status_code=400,
                )

            # 3. Append deduction to immutable ledger
            ledger_entry = PointsLedgerModel(
                user_id=user.id,
                job_id=None,
                milestone_tier=0,
                points_awarded=-cost,
                multiplier_applied=1.0,
                reason="redemption_quota_bump_2",
                created_at=utc_now(),
            )
            session.add(ledger_entry)
            session.commit()
            session.refresh(ledger_entry)

            new_balance = PointsEngine.get_user_points_balance(session, user.id)
            quota_bonus = PointsEngine.get_user_monthly_quota_bonus(session, user.id)
            effective_quota = BillingService.get_effective_quota_limit(user.id, session)

            logger.info(
                f"[Quota Redeemed] user_id={user.id}, spent={cost} points, new_balance={new_balance}, "
                f"current_month_bonus=+{quota_bonus}, effective_quota={effective_quota}"
            )

            return {
                "success": True,
                "message": f"Successfully redeemed +{amount} repository analysis quota for {cost} points!",
                "points_spent": cost,
                "new_balance": new_balance,
                "monthly_quota_bonus": quota_bonus,
                "effective_monthly_quota": effective_quota,
                "ledger_id": ledger_entry.id,
            }

    @staticmethod
    def get_user_badges(session: Session, user_id: int) -> List[Dict[str, Any]]:
        """
        Evaluates real achievement badges against actual database attempts and solve history.
        """
        # Metrics Extraction
        verified_attempts = (
            session.query(MilestoneAttemptModel)
            .filter(
                MilestoneAttemptModel.user_id == user_id,
                MilestoneAttemptModel.status == "structurally_verified",
            )
            .all()
        )
        total_solves = len(verified_attempts)

        zero_hint_solves = sum(
            1 for a in verified_attempts
            if a.hint_level_revealed == 0 and not a.implementation_revealed
        )

        distinct_repos = len(set(a.job_id for a in verified_attempts))
        lifetime_points = PointsEngine.get_user_lifetime_points(session, user_id)

        # 5 Concrete Badges
        badges = [
            {
                "id": "first_milestone",
                "name": "First Milestone",
                "tagline": "Dossier Initiate",
                "description": "Solved your very first architectural milestone.",
                "icon": "🎯",
                "category": "milestones",
                "earned": total_solves >= 1,
                "current_progress": min(1, total_solves),
                "target": 1,
                "progress_pct": min(100, int((total_solves / 1) * 100)),
            },
            {
                "id": "zero_hint_streak_5",
                "name": "Zero-Hint Ace",
                "tagline": "Pure Intuition",
                "description": "Solved 5 milestones cleanly without unlocking any progressive hints.",
                "icon": "⚡",
                "category": "mastery",
                "earned": zero_hint_solves >= 5,
                "current_progress": min(5, zero_hint_solves),
                "target": 5,
                "progress_pct": min(100, int((zero_hint_solves / 5) * 100)),
            },
            {
                "id": "repo_explorer",
                "name": "Repo Explorer",
                "tagline": "Multi-System Pioneer",
                "description": "Analyzed and solved milestones across 3 or more distinct repositories.",
                "icon": "🧭",
                "category": "exploration",
                "earned": distinct_repos >= 3,
                "current_progress": min(3, distinct_repos),
                "target": 3,
                "progress_pct": min(100, int((distinct_repos / 3) * 100)),
            },
            {
                "id": "century_club",
                "name": "Century Club",
                "tagline": "Triple Digit Builder",
                "description": "Accumulated 100 or more lifetime milestone points in the ledger.",
                "icon": "🏆",
                "category": "points",
                "earned": lifetime_points >= 100,
                "current_progress": min(100, lifetime_points),
                "target": 100,
                "progress_pct": min(100, int((lifetime_points / 100) * 100)),
            },
            {
                "id": "architect_master",
                "name": "Architect Master",
                "tagline": "Grandmaster of Code",
                "description": "Completed and structurally verified 10 milestones across all projects.",
                "icon": "💎",
                "category": "mastery",
                "earned": total_solves >= 10,
                "current_progress": min(10, total_solves),
                "target": 10,
                "progress_pct": min(100, int((total_solves / 10) * 100)),
            },
        ]

        return badges

    @staticmethod
    def get_leaderboard(
        session: Session,
        current_user_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Calculates aggregate points across all users and produces a paginated leaderboard
        with current user's pinned overall rank.
        """
        # Query total lifetime points per user
        stmt = (
            select(
                UserModel.id,
                UserModel.github_username,
                UserModel.avatar_url,
                func.coalesce(func.sum(PointsLedgerModel.points_awarded), 0).label("total_points"),
            )
            .outerjoin(PointsLedgerModel, (PointsLedgerModel.user_id == UserModel.id) & (PointsLedgerModel.points_awarded > 0))
            .group_by(UserModel.id, UserModel.github_username, UserModel.avatar_url)
            .order_by(desc("total_points"), UserModel.id.asc())
        )
        all_ranks = list(session.execute(stmt).all())

        # Determine overall user rank
        user_rank = 1
        user_points = 0
        for idx, row in enumerate(all_ranks, start=1):
            if row[0] == current_user_id:
                user_rank = idx
                user_points = int(row[3])
                break

        # Paginated slice
        paged_rows = all_ranks[offset : offset + limit]
        entries = []
        for idx, row in enumerate(paged_rows, start=offset + 1):
            entries.append({
                "rank": idx,
                "user_id": row[0],
                "username": row[1],
                "avatar_url": row[2],
                "points": int(row[3]),
                "is_current_user": (row[0] == current_user_id),
            })

        return {
            "total_users": len(all_ranks),
            "current_user_rank": user_rank,
            "current_user_points": user_points,
            "leaderboard": entries,
        }

    @staticmethod
    def get_user_ledger(
        session: Session,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> List[PointsLedgerModel]:
        """Retrieves paginated audit ledger history for a specific user, ordered newest first."""
        stmt = (
            select(PointsLedgerModel)
            .where(PointsLedgerModel.user_id == user_id)
            .order_by(PointsLedgerModel.created_at.desc(), PointsLedgerModel.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(session.scalars(stmt).all())
