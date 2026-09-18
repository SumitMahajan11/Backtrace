"""API Router for Points Economy, Balance Inquiries, Redemptions, Badges, and Leaderboard (Prompt 23 & 24)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.models.db import PointsLedgerModel, UserModel
from app.services.points_engine import PointsEngine, PointsRedemptionError
from app.storage.analysis_job_repository import AnalysisJobRepository

router = APIRouter(prefix="/points", tags=["Points Economy"])


class PointsLedgerItem(BaseModel):
    """Serialized ledger audit event."""
    id: int
    user_id: int
    job_id: Optional[int]
    milestone_tier: int
    points_awarded: int
    multiplier_applied: float
    reason: str
    created_at: str


class PointsBalanceResponse(BaseModel):
    """Summary of active, lifetime, and expired points."""
    user_id: int
    username: str
    balance: int
    lifetime_points: int
    expired_points: int


def _serialize_ledger_entry(entry: PointsLedgerModel) -> Dict[str, Any]:
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "job_id": entry.job_id,
        "milestone_tier": entry.milestone_tier,
        "points_awarded": entry.points_awarded,
        "multiplier_applied": entry.multiplier_applied,
        "reason": entry.reason,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


@router.get("/balance", response_model=PointsBalanceResponse, summary="Get Current Authenticated User Point Balance")
def get_current_user_balance(
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> PointsBalanceResponse:
    """
    Returns active (unexpired) points balance, lifetime points, and expired points
    for the authenticated user. Derived dynamically from the append-only ledger.
    """
    balance = PointsEngine.get_user_points_balance(session, current_user.id)
    lifetime = PointsEngine.get_user_lifetime_points(session, current_user.id)
    expired = PointsEngine.get_user_expired_points(session, current_user.id)

    return PointsBalanceResponse(
        user_id=current_user.id,
        username=current_user.github_username,
        balance=balance,
        lifetime_points=lifetime,
        expired_points=expired,
    )


@router.get("/ledger", summary="Get Authenticated User Points Audit Ledger")
def get_current_user_ledger(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Returns paginated points ledger audit log for authenticated user.
    """
    entries = PointsEngine.get_user_ledger(session, current_user.id, limit=limit, offset=offset)
    balance = PointsEngine.get_user_points_balance(session, current_user.id)

    return {
        "user_id": current_user.id,
        "balance": balance,
        "total_entries": len(entries),
        "ledger": [_serialize_ledger_entry(e) for e in entries],
    }


@router.post("/redeem/quota", summary="Redeem Points for +2 Monthly Analysis Quota")
def redeem_analysis_quota(
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Executes atomic redemption of 100 points for +2 repository analysis quota.
    Deducts points via negative PointsLedgerModel entry and updates real monthly quota.
    Guarded against double-spend races, insufficient balance, and Pro-tier redundancy.
    """
    try:
        result = PointsEngine.redeem_quota_perk(session, current_user)
        return result
    except PointsRedemptionError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.message,
        )


@router.get("/badges", summary="Get Authenticated User Achievement Badges")
def get_user_badges(
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Returns the fixed set of authentic badges with real progression and unlock status.
    """
    badges = PointsEngine.get_user_badges(session, current_user.id)
    earned_count = sum(1 for b in badges if b.get("earned"))

    return {
        "user_id": current_user.id,
        "total_badges": len(badges),
        "earned_badges": earned_count,
        "badges": badges,
    }


@router.get("/leaderboard", summary="Get Global Platform Leaderboard")
def get_leaderboard(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Returns platform-wide leaderboard ranked by total milestone points.
    Includes authenticated user's pinned overall rank.
    """
    data = PointsEngine.get_leaderboard(session, current_user.id, limit=limit, offset=offset)
    return data


@router.get("/user/{target_user_id}", summary="Get Points Summary by User ID (IDOR Protected)")
def get_user_points_by_id(
    target_user_id: int,
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Retrieves point balance and ledger for target user ID.
    Strict IDOR check: Users may only access their own point records unless admin.
    """
    if target_user_id != current_user.id and not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You cannot view another user's points ledger",
        )

    balance = PointsEngine.get_user_points_balance(session, target_user_id)
    lifetime = PointsEngine.get_user_lifetime_points(session, target_user_id)
    expired = PointsEngine.get_user_expired_points(session, target_user_id)
    entries = PointsEngine.get_user_ledger(session, target_user_id, limit=20)
    badges = PointsEngine.get_user_badges(session, target_user_id)

    return {
        "user_id": target_user_id,
        "balance": balance,
        "lifetime_points": lifetime,
        "expired_points": expired,
        "badges": badges,
        "recent_ledger": [_serialize_ledger_entry(e) for e in entries],
    }


@router.get("/job/{job_id}", summary="Get Milestone Points Ledger for Job (IDOR Protected)")
def get_job_points_ledger(
    job_id: int,
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Retrieves all points ledger entries associated with a specific job ID.
    Strict IDOR check: Job must belong to authenticated user.
    """
    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")

    if job.user_id != current_user.id and not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    stmt = (
        select(PointsLedgerModel)
        .where(PointsLedgerModel.job_id == job_id, PointsLedgerModel.user_id == current_user.id)
        .order_by(PointsLedgerModel.created_at.desc())
    )
    entries = list(session.scalars(stmt).all())

    return {
        "job_id": job_id,
        "total_awarded": sum(e.points_awarded for e in entries if e.points_awarded > 0),
        "ledger": [_serialize_ledger_entry(e) for e in entries],
    }
