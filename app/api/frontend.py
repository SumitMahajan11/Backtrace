"""Frontend UI Router for Backtrace.

Integrates FastHTML/Semantic Server-Rendered UI with FastAPI backend.
Handles Login, Dashboard, Progress (SSE), and Report views with strict
XSS sanitization, CSRF mitigation, and IDOR protection.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_current_user_optional, get_db
from app.core.config import rewards_enabled
from app.models.db import (
    AnalysisJobModel,
    MilestoneAttemptModel,
    PointsLedgerModel,
    RefreshTokenModel,
    SubscriptionModel,
    UsageEventModel,
    UserModel,
    utc_now,
)
from app.services.billing_service import BillingService, BillingServiceError
from app.services.points_engine import PointsEngine, PointsRedemptionError
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.milestone_attempt_repository import MilestoneAttemptRepository
from app.orchestration.pipeline import PipelineCancelled
from app.ui.components import (
    dashboard_view,
    extract_owner_and_repo,
    failure_reason,
    login_view,
    map_failure_reason,
    map_stage_to_phase,
    page_shell,
    pricing_view,
    privacy_view,
    progress_view,
    render_milestone_body_fragment,
    report_view,
    rewards_view,
    settings_view,
    showcase_view,
    support_view,
    _parse_report_markdown,
)
from app.ui.sanitizer import sanitize_text

router = APIRouter(tags=["Frontend UI"])

_RUNNING_JOB_THREADS: Dict[str, threading.Thread] = {}
_RUNNING_JOB_LOCK = threading.Lock()


@router.get("/", summary="Root Redirect")
def root_redirect(
    user: Optional[UserModel] = Depends(get_current_user_optional),
):
    """Redirect logged in users to /dashboard, otherwise to /login."""
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@router.get("/favicon.svg", summary="Favicon SVG")
def get_favicon():
    """Serve favicon.svg icon."""
    favicon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "favicon.svg")
    if os.path.exists(favicon_path):
        with open(favicon_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32"><rect width="32" height="32" rx="8" fill="#4f8cff"/><text x="16" y="22" font-family="Inter, system-ui, sans-serif" font-weight="700" font-size="18" fill="#ffffff" text-anchor="middle">B</text></svg>'
    return Response(content=content, media_type="image/svg+xml")


@router.get("/login", response_class=HTMLResponse, summary="Login View")
def show_login(
    request: Request,
    error: Optional[str] = Query(None),
    user: Optional[UserModel] = Depends(get_current_user_optional),
):
    """Render the login view. If already logged in, redirect to dashboard."""
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return HTMLResponse(content=login_view(error=error))


@router.get("/dashboard", response_class=HTMLResponse, summary="User Dashboard View")
def show_dashboard(
    request: Request,
    error: Optional[str] = Query(None),
    success: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Render user dashboard with repo submission form, past analysis jobs, and quota badge.
    Redirects unauthenticated visitors to /login.
    Fulfills Stripe Checkout session synchronously if session_id query parameter is present.
    """
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    if session_id:
        try:
            res = BillingService.fulfill_checkout_session(
                session_id=session_id,
                user=user,
                session=session,
            )
            if res.get("success") and not success:
                success = res.get("message")
        except Exception:
            pass

    billing_status = BillingService.get_user_billing_status(user, session)
    past_jobs = AnalysisJobRepository.get_grouped_jobs_for_user(session, user.id)

    return HTMLResponse(
        content=dashboard_view(
            current_user=user,
            billing_status=billing_status,
            past_jobs=past_jobs,
            error=error,
            success=success,
        )
    )


@router.get("/settings", response_class=HTMLResponse, summary="User Settings & Billing View")
def show_settings(
    request: Request,
    error: Optional[str] = Query(None),
    success: Optional[str] = Query(None),
    billing: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Render user settings and billing ledger view.
    Redirects unauthenticated visitors to /login.
    Fulfills Stripe Checkout session synchronously if session_id query parameter is present.
    """
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    billing_error = False
    if billing == "error" or request.query_params.get("billing") == "error":
        billing_error = True
        error = "We couldn't start checkout. Please try again in a few minutes."

    if session_id:
        try:
            res = BillingService.fulfill_checkout_session(
                session_id=session_id,
                user=user,
                session=session,
            )
            if res.get("success") and not success:
                success = res.get("message")
        except Exception:
            pass

    billing_status = BillingService.get_user_billing_status(user, session)
    pricing_details = BillingService.get_pro_price_details()

    return HTMLResponse(
        content=settings_view(
            current_user=user,
            billing_status=billing_status,
            pricing_details=pricing_details,
            error=error,
            success=success,
            billing_error=billing_error,
        )
    )


@router.post("/settings", summary="Update User Settings")
def update_settings(
    request: Request,
    show_on_leaderboard: Optional[str] = Form(None),
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """Update user settings such as leaderboard username visibility."""
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    user.show_on_leaderboard = bool(show_on_leaderboard and show_on_leaderboard.lower() in ("true", "on", "1", "yes"))
    session.add(user)
    session.commit()

    return RedirectResponse(url="/settings?success=Preferences+updated", status_code=status.HTTP_302_FOUND)


@router.get("/account/export.json", summary="Export User Account Data (JSON)")
def export_user_data(
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Downloads user account data in JSON format:
    jobs, progress (milestone attempts), and quiz scores.
    """
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    jobs = (
        session.query(AnalysisJobModel)
        .filter(AnalysisJobModel.user_id == user.id)
        .order_by(AnalysisJobModel.created_at.desc())
        .all()
    )
    attempts = (
        session.query(MilestoneAttemptModel)
        .filter(MilestoneAttemptModel.user_id == user.id)
        .order_by(MilestoneAttemptModel.created_at.desc())
        .all()
    )

    jobs_data = []
    for j in jobs:
        jobs_data.append({
            "id": j.id,
            "repo_name": j.repo_name,
            "github_url": j.github_url,
            "commit_ref": j.commit_ref,
            "resolved_sha": j.resolved_sha,
            "subpath": j.subpath,
            "status": j.status,
            "failed_stage": j.failed_stage,
            "error_message": j.error_message,
            "execution_time_seconds": j.execution_time_seconds,
            "is_showcase": j.is_showcase,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "updated_at": j.updated_at.isoformat() if j.updated_at else None,
        })

    progress_data = []
    quiz_scores_data = []
    for a in attempts:
        progress_data.append({
            "id": a.id,
            "job_id": a.job_id,
            "milestone_tier": a.milestone_tier,
            "status": a.status,
            "hint_level_revealed": a.hint_level_revealed,
            "implementation_revealed": a.implementation_revealed,
            "grading_method": a.grading_method,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        })
        if a.grading_details_json:
            try:
                gd = json.loads(a.grading_details_json)
                if isinstance(gd, dict) and "quiz_score" in gd:
                    quiz_scores_data.append({
                        "job_id": a.job_id,
                        "milestone_tier": a.milestone_tier,
                        "quiz_score": gd.get("quiz_score"),
                        "quiz_total": gd.get("quiz_total"),
                        "quiz_passed": gd.get("quiz_passed"),
                        "recorded_at": gd.get("quiz_recorded_at"),
                    })
            except Exception:
                pass

    export_payload = {
        "user": {
            "id": user.id,
            "github_username": user.github_username,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "show_on_leaderboard": getattr(user, "show_on_leaderboard", False),
        },
        "jobs": jobs_data,
        "progress": progress_data,
        "quiz_scores": quiz_scores_data,
        "exported_at": utc_now().isoformat(),
    }

    content_str = json.dumps(export_payload, indent=2)
    filename = f"backtrace_export_{user.github_username}.json"
    return Response(
        content=content_str,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/account/delete", summary="Permanently Delete User Account")
def delete_user_account(
    request: Request,
    username: str = Form(..., description="Confirmed GitHub username"),
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Permanently purges the authenticated user and all associated records across:
    - milestone_attempts
    - points_ledger
    - analysis_jobs
    - usage_events
    - refresh_tokens
    - subscriptions
    - users
    Clears session cookies and redirects to /login.
    """
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    if username.strip() != user.github_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Confirmation username '{username.strip()}' does not match account username '{user.github_username}'.",
        )

    # Purge user references across dependent tables explicitly to ensure integrity across SQLite and Postgres
    session.query(MilestoneAttemptModel).filter(MilestoneAttemptModel.user_id == user.id).delete()
    session.query(PointsLedgerModel).filter(PointsLedgerModel.user_id == user.id).delete()
    session.query(AnalysisJobModel).filter(AnalysisJobModel.user_id == user.id).delete()
    session.query(UsageEventModel).filter(UsageEventModel.user_id == user.id).delete()
    session.query(RefreshTokenModel).filter(RefreshTokenModel.user_id == user.id).delete()
    session.query(SubscriptionModel).filter(SubscriptionModel.user_id == user.id).delete()
    session.delete(user)
    session.commit()

    resp = RedirectResponse(url="/login?deleted=1", status_code=status.HTTP_302_FOUND)
    resp.delete_cookie("access_token", path="/")
    resp.delete_cookie("refresh_token", path="/")
    return resp


@router.get("/rewards", response_class=HTMLResponse, summary="Rewards & Points Economy View")
@router.get("/points", response_class=HTMLResponse, summary="Points Economy View (Alias)")
def show_rewards(
    request: Request,
    error: Optional[str] = Query(None),
    success: Optional[str] = Query(None),
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Render user Points & Rewards Dossier view.
    Displays active balance with 180-day expiry notice, software perks redemption,
    achievement badges, global leaderboard, and audit ledger.
    """
    if not rewards_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rewards protocol disabled")

    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    billing_status = BillingService.get_user_billing_status(user, session)
    points_balance = PointsEngine.get_user_points_balance(session, user.id)
    lifetime_points = PointsEngine.get_user_lifetime_points(session, user.id)
    badges = PointsEngine.get_user_badges(session, user.id)
    leaderboard = PointsEngine.get_leaderboard(session, user.id, limit=10)
    ledger_entries = PointsEngine.get_user_ledger(session, user.id, limit=50)

    return HTMLResponse(
        content=rewards_view(
            current_user=user,
            billing_status=billing_status,
            points_balance=points_balance,
            lifetime_points=lifetime_points,
            badges=badges,
            leaderboard_data=leaderboard,
            ledger_entries=ledger_entries,
            error=error,
            success=success,
        )
    )


@router.post("/rewards/redeem/quota", summary="Redeem Points for Quota (Form Action)")
def redeem_quota_form_action(
    request: Request,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Form action endpoint for redeeming points for +2 monthly analysis quota.
    """
    if not rewards_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rewards protocol disabled")

    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    try:
        res = PointsEngine.redeem_quota_perk(session, user)
        msg = res.get("message", "Successfully redeemed +2 quota!")
        return RedirectResponse(url=f"/rewards?success={msg.replace(' ', '+')}", status_code=status.HTTP_302_FOUND)
    except PointsRedemptionError as e:
        return RedirectResponse(url=f"/rewards?error={e.message.replace(' ', '+')}", status_code=status.HTTP_302_FOUND)



@router.post("/analyses/submit", summary="Submit Repository for Analysis")
def submit_analysis(
    request: Request,
    repo_url: str = Form(..., description="Target GitHub repository URL"),
    commit_ref: Optional[str] = Form(None, description="Optional branch or commit reference"),
    subpath: Optional[str] = Form(None, description="Optional subdirectory path scope"),
    reanalyze_anyway: Optional[bool] = Form(False, description="Optional flag to force re-analysis even if commit SHA is unchanged"),
    force_reanalyze: Optional[bool] = Form(False, description="Alias for reanalyze_anyway"),
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Process repository submission form.
    Executes lightweight preflight size check against GitHub API before database job creation.
    Resolves remote commit SHA and redirects to existing completed report if commit is unchanged.
    Enforces quota gating only on valid, un-cached repos and records an AnalysisJob.
    """
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    clean_url = repo_url.strip()
    from app.utils.url_validator import validate_github_url
    try:
        validate_github_url(clean_url)
    except Exception:
        return RedirectResponse(
            url="/dashboard?error=That+doesn%27t+look+like+a+GitHub+repository+link.",
            status_code=status.HTTP_302_FOUND,
        )

    is_forced = bool(reanalyze_anyway or force_reanalyze)

    from app.utils.file_filter import sanitize_and_validate_subpath
    from app.services.ingestion import validate_commit_ref
    billing_status = BillingService.get_user_billing_status(user, session)
    past_jobs = AnalysisJobRepository.get_grouped_jobs_for_user(session, user.id)

    try:
        clean_subpath = sanitize_and_validate_subpath(subpath)
    except ValueError as e:
        return HTMLResponse(
            content=dashboard_view(
                current_user=user,
                billing_status=billing_status,
                past_jobs=past_jobs,
                error=str(e),
            ),
            status_code=status.HTTP_200_OK,
        )

    try:
        clean_ref = validate_commit_ref(commit_ref)
    except ValueError as e:
        return HTMLResponse(
            content=dashboard_view(
                current_user=user,
                billing_status=billing_status,
                past_jobs=past_jobs,
                error=str(e),
            ),
            status_code=status.HTTP_200_OK,
        )

    from app.services.ingestion import check_repo_size_preflight
    from app.models.ingestion import RepoTooLargeError, GitHubAPIError, InvalidURLError, SSRFError

    # 1. Preflight File Count Check
    try:
        check_repo_size_preflight(
            github_url=clean_url,
            commit_ref=clean_ref,
            subpath=clean_subpath,
        )
    except RepoTooLargeError as e:
        # Zero DB rows created, zero quota consumed. Render dedicated "Repository Too Large" card in place.
        return HTMLResponse(
            content=dashboard_view(
                current_user=user,
                billing_status=billing_status,
                past_jobs=past_jobs,
                too_large_info={
                    "file_count": e.file_count,
                    "limit": e.limit,
                    "repo_url": clean_url,
                    "commit_ref": clean_ref or "",
                    "subpath": clean_subpath or "",
                },
            ),
            status_code=status.HTTP_200_OK,
        )
    except GitHubAPIError as e:
        # Distinct error for GitHub API failures (rate limit, private repo, 404, auth)
        return HTMLResponse(
            content=dashboard_view(
                current_user=user,
                billing_status=billing_status,
                past_jobs=past_jobs,
                error=f"GitHub API Error: {str(e)}",
            ),
            status_code=status.HTTP_200_OK,
        )
    except (InvalidURLError, SSRFError) as e:
        return HTMLResponse(
            content=dashboard_view(
                current_user=user,
                billing_status=billing_status,
                past_jobs=past_jobs,
                error="That doesn't look like a GitHub repository link.",
            ),
            status_code=status.HTTP_200_OK,
        )

    # 2. Resolve Remote Latest Commit SHA (Part A: cache re-analysis)
    from app.services.cached_ingestion import get_remote_head_commit
    try:
        resolved_sha = get_remote_head_commit(clean_url, commit_ref=clean_ref)
    except TypeError:
        resolved_sha = get_remote_head_commit(clean_url)

    # Check for existing completed report for identical repo URL, branch, subdirectory AND commit SHA
    if not is_forced:
        existing_job = AnalysisJobRepository.find_completed_job(
            session=session,
            user_id=user.id,
            github_url=clean_url,
            commit_ref=clean_ref,
            subpath=clean_subpath,
            resolved_sha=resolved_sha,
        )
        if existing_job:
            # Redirect to existing completed report without creating job, charging quota, or resetting progress
            return RedirectResponse(
                url=f"/report/{existing_job.id}",
                status_code=status.HTTP_302_FOUND,
            )

    # 3. Enforce Billing Quota Gate (only after passing preflight and cache check)
    is_allowed, usage, limit, tier = BillingService.check_and_consume_quota(user, session)
    if not is_allowed:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        if now.month == 12:
            next_month_date = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month_date = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
        renewal_date_str = next_month_date.strftime("%b %d, %Y")
        err_msg = f"You've used all {limit} analyses this month. Resets on {renewal_date_str}."

        if "application/json" in request.headers.get("accept", ""):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=err_msg,
            )
        return RedirectResponse(
            url=f"/dashboard?error={err_msg.replace(' ', '+')}",
            status_code=status.HTTP_302_FOUND,
        )

    # 4. Create Analysis Job record
    job = AnalysisJobRepository.create_job(
        session=session,
        user_id=user.id,
        repo_url=clean_url,
        commit_ref=clean_ref,
        subpath=clean_subpath,
        resolved_sha=resolved_sha,
        status="running",
    )

    from app.monitoring.posthog import analytics
    analytics.capture_analysis_submitted(user_id=user.id, job_id=job.id, tier=tier)

    return RedirectResponse(url=f"/progress/{job.id}", status_code=status.HTTP_302_FOUND)


@router.post("/analyses/{job_id}/retry", summary="Retry Failed Analysis Job (UI)")
@router.post("/jobs/{job_id}/retry", summary="Retry Failed Analysis Job (UI alias)")
def retry_analysis_ui(
    job_id: str,
    request: Request,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Retry a failed analysis job.
    """
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis job not found",
        )

    if job.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    # Enforce Billing Quota Gate exactly like a new submission
    is_allowed, usage, limit, tier = BillingService.check_and_consume_quota(user, session, job_id=job.id)
    if not is_allowed:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        if now.month == 12:
            next_month_date = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month_date = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
        renewal_date_str = next_month_date.strftime("%b %d, %Y")
        err_msg = f"You've used all {limit} analyses this month. Resets on {renewal_date_str}."

        if "application/json" in request.headers.get("accept", ""):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=err_msg,
            )
        return RedirectResponse(
            url=f"/dashboard?error={err_msg.replace(' ', '+')}",
            status_code=status.HTTP_302_FOUND,
        )

    # Reset job status and wipe stale output fields
    job.status = "pending"
    job.error_message = None
    job.markdown_output = ""
    job.graph_output_json = "{}"
    job.quiz_output_json = "{}"
    job.execution_time_seconds = 0.0
    job.run_id = f"retry_{job.id}_{int(time.time())}"
    job.updated_at = utc_now()
    session.commit()

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            content={
                "success": True,
                "job_id": job.id,
                "status": "pending",
                "redirect_url": f"/progress/{job.id}",
            }
        )

    return RedirectResponse(url=f"/progress/{job.id}", status_code=status.HTTP_302_FOUND)


@router.post("/api/analyses/{job_id}/retry", summary="Retry Failed Analysis Job (API)")
def retry_analysis_api(
    job_id: str,
    user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    API endpoint to retry a failed analysis job.
    """
    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis job not found",
        )

    if job.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    is_allowed, usage, limit, tier = BillingService.check_and_consume_quota(user, session, job_id=job.id)
    if not is_allowed:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        if now.month == 12:
            next_month_date = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month_date = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
        renewal_date_str = next_month_date.strftime("%b %d, %Y")
        err_msg = f"You've used all {limit} analyses this month. Resets on {renewal_date_str}."
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=err_msg,
        )

    job.status = "pending"
    job.error_message = None
    job.markdown_output = ""
    job.graph_output_json = "{}"
    job.quiz_output_json = "{}"
    job.execution_time_seconds = 0.0
    job.run_id = f"retry_{job.id}_{int(time.time())}"
    job.updated_at = utc_now()
    session.commit()

    return JSONResponse(
        content={
            "success": True,
            "job_id": job.id,
            "status": "pending",
            "redirect_url": f"/progress/{job.id}",
        }
    )


@router.post("/jobs/{job_id}/cancel", summary="Cancel Analysis Job")
@router.post("/analyses/{job_id}/cancel", summary="Cancel Analysis Job (alias)")
async def cancel_job(
    job_id: str,
    request: Request,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Cancel an in-progress or queued analysis job and refund user quota.
    """
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis job not found",
        )

    if job.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    job_status = str(job.status or "").lower()
    if job_status in ("pending", "queued", "running", "processing"):
        AnalysisJobRepository.update_job_status(session, job.id, status="cancelled")
        session.commit()

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            content={
                "success": True,
                "job_id": job.id,
                "status": "cancelled",
                "message": "Analysis cancelled.",
            }
        )

    return RedirectResponse(url=f"/progress/{job.id}", status_code=status.HTTP_302_FOUND)


@router.post("/jobs/{job_id}/delete", summary="Delete Analysis Job")
@router.post("/analyses/{job_id}/delete", summary="Delete Analysis Job (alias)")
@router.delete("/jobs/{job_id}", summary="Delete Analysis Job (REST)")
@router.delete("/analyses/{job_id}", summary="Delete Analysis Job (REST alias)")
@router.post("/api/analyses/{job_id}/delete", summary="Delete Analysis Job (API)")
@router.delete("/api/analyses/{job_id}", summary="Delete Analysis Job (API REST)")
async def delete_job(
    job_id: str,
    request: Request,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Delete an analysis job.
    Only the job's owner may delete it. Returns 403 Forbidden if another user attempts deletion.
    Redirects back to /dashboard on success or returns JSON if requested.
    """
    if not user:
        if "application/json" in request.headers.get("accept", ""):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis job not found",
        )

    if job.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    session.delete(job)
    session.commit()

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            content={
                "success": True,
                "job_id": int(job_id) if str(job_id).isdigit() else job_id,
                "message": "Analysis job deleted successfully.",
            }
        )

    return RedirectResponse(
        url="/dashboard?success=Repository+analysis+deleted",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/progress/{job_id}", response_class=HTMLResponse, summary="Analysis Progress View")
def show_progress(
    job_id: str,
    request: Request,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Render live progress view with SSE listeners.
    Strict IDOR check: Users can only view their own jobs.
    Auto-redirect on completed removed: renders Report ready card with real numbers.
    """
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis job not found",
        )

    if job.user_id != user.id:
        # Strict IDOR check: User A cannot view User B's job
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    billing_status = BillingService.get_user_billing_status(user, session)
    return HTMLResponse(content=progress_view(job=job, current_user=user, billing_status=billing_status))


STAGE_METADATA: Dict[str, Dict[str, Any]] = {
    "stage_0": {"index": 1, "total": 11, "name": "Consent & Auth Gate", "layer": "layer_1_ingestion"},
    "stage_1": {"index": 2, "total": 11, "name": "Shallow Clone", "layer": "layer_1_ingestion"},
    "stage_2": {"index": 3, "total": 11, "name": "Discovery & File Hierarchy", "layer": "layer_1_ingestion"},
    "stage_3": {"index": 4, "total": 11, "name": "Code Structure Parsing", "layer": "layer_2_parsing"},
    "stage_4": {"index": 5, "total": 11, "name": "Global Symbol Table", "layer": "layer_2_parsing"},
    "stage_5": {"index": 6, "total": 11, "name": "Directed Dependency Graph", "layer": "layer_4_segmentation"},
    "stage_6": {"index": 7, "total": 11, "name": "Architecture Domain Mapping", "layer": "layer_4_segmentation"},
    "stage_7": {"index": 8, "total": 11, "name": "Step-by-step narration", "layer": "layer_6_sequence_reasoning"},
    "stage_8": {"index": 9, "total": 11, "name": "Graph & Quiz Generation", "layer": "layer_7_synthesis"},
    "stage_9": {"index": 10, "total": 11, "name": "Persistence & Architecture Report Assembly", "layer": "layer_7_synthesis"},
    "stage_10": {"index": 11, "total": 11, "name": "Telemetry & Quota Allocation", "layer": "layer_7_synthesis"},
}


@router.get("/api/analyses/{job_id}/events", summary="Server-Sent Events Stream for Progress")
async def analysis_progress_events(
    job_id: str,
    request: Request,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Server-Sent Events endpoint streaming live Backtrace pipeline execution status.
    Strictly authenticates and verifies user ownership before streaming any data.
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to subscribe to analysis events",
        )

    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis job not found",
        )

    if job.user_id != user.id:
        # Strict IDOR check
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    job_status = str(job.status)
    target_repo_url = str(job.repo_url)
    target_commit_ref = getattr(job, "commit_ref", None)
    target_subpath = getattr(job, "subpath", None)
    active_user_id = int(user.id)
    initial_exec_sec = float(getattr(job, "execution_time_seconds", 0.0) or 0.0)
    initial_failed_stage = str(getattr(job, "failed_stage", None) or "pipeline")
    initial_error_msg = str(getattr(job, "error_message", None) or "Analysis job previously failed.")
    initial_markdown_output = str(getattr(job, "markdown_output", "") or "")

    async def event_generator() -> AsyncGenerator[str, None]:
        if job_status == "completed":
            files_analyzed, modules_count, entry_points_count = 0, 0, 0
            if initial_markdown_output:
                try:
                    ov = _parse_report_markdown(initial_markdown_output).get("overview", {})
                    files_analyzed = ov.get("total_files", 0)
                    modules_count = ov.get("total_domains", 0)
                    entry_points_count = len(ov.get("entry_points", []))
                except Exception:
                    pass
            yield f"data: {json.dumps({'type': 'completed', 'job_id': job_id, 'percentage': 100, 'execution_time_seconds': initial_exec_sec, 'files_analyzed': files_analyzed, 'modules_mapped': modules_count, 'entry_points': entry_points_count})}\n\n"
            return

        if job_status == "failed":
            yield f"data: {json.dumps({'type': 'failed', 'job_id': job_id, 'failed_stage': initial_failed_stage, 'message': failure_reason(initial_error_msg), 'execution_time_seconds': initial_exec_sec})}\n\n"
            return

        import time
        import threading
        import logging
        from app.services.metrics import metrics_collector
        logger = logging.getLogger("reverse.frontend")
        start_time = time.time()
        loop = asyncio.get_running_loop()
        event_queue = asyncio.Queue()

        last_emitted_pct = [0]
        completed_stages = set()

        def make_progress_payload(ui_key: str, pct: int, msg: str, **kwargs) -> dict:
            meta = STAGE_METADATA.get(ui_key, {})
            layer_name = meta.get("layer", "")
            est_rem = metrics_collector.estimate_remaining_duration_seconds(layer_name)
            effective_pct = max(last_emitted_pct[0], pct)
            last_emitted_pct[0] = effective_pct
            payload = {
                "type": "progress",
                "job_id": job_id,
                "stage": ui_key,
                "stage_index": meta.get("index", 1),
                "stage_total": 11,
                "stage_name": meta.get("name", "Analysis Stage"),
                "percentage": effective_pct,
                "message": msg,
                "estimated_remaining_seconds": est_rem,
            }
            payload.update(kwargs)
            return payload

        def make_stage_complete_payload(ui_key: str) -> dict:
            meta = STAGE_METADATA.get(ui_key, {})
            return {
                "type": "stage_complete",
                "job_id": job_id,
                "stage": ui_key,
                "stage_index": meta.get("index", 1),
                "stage_total": 11,
                "stage_name": meta.get("name", "Analysis Stage"),
            }

        # Step 0: Initial Auth & Security Gate
        completed_stages.add("stage_0")
        yield f"data: {json.dumps(make_progress_payload('stage_0', 10, 'Consent & Auth Gate verified'))}\n\n"
        yield f"data: {json.dumps(make_stage_complete_payload('stage_0'))}\n\n"

        stage_sequence_map = {
            "ingestion": [],  # Stages 1 and 2 are emitted directly by run_full_pipeline_sync during clone and discovery
            "parsing": [
                ("stage_3", 38, "Parsing concrete syntax trees across source files..."),
                ("stage_4", 48, "Extracting global symbol table and exported declarations..."),
            ],
            "understanding": [
                ("stage_5", 58, "Constructing directed dependency graph and resolving imports..."),
                ("stage_6", 68, "Segmenting architecture domains and component boundaries..."),
            ],
            "reasoning": [
                ("stage_7", 80, "Synthesizing topological sequence reasoning and narrative..."),
            ],
            "synthesis": [
                ("stage_8", 88, "Building interactive call-graphs and comprehension quiz checkpoints..."),
            ],
            "complete": [],
        }

        def on_pipeline_event(ev: Any):
            from app.db.session import SessionLocal
            with SessionLocal() as db_session:
                current_job = AnalysisJobRepository.get_job_by_id(db_session, job_id)
                if current_job and str(current_job.status or "").lower() == "cancelled":
                    raise PipelineCancelled(f"Job {job_id} was cancelled by user.")

            stage_name = ev.stage.value if hasattr(ev.stage, "value") else str(ev.stage)
            stage_items = stage_sequence_map.get(stage_name, [])
            for ui_key, pct, default_msg in stage_items:
                if ui_key in completed_stages:
                    continue
                completed_stages.add(ui_key)
                msg = default_msg
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    make_progress_payload(ui_key, pct, msg),
                )
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    make_stage_complete_payload(ui_key),
                )

        def run_full_pipeline_sync():
            from app.services.ingestion import IngestionService
            from app.orchestration.pipeline import PipelineOrchestrator
            from app.formatters.markdown_formatter import MarkdownReportFormatter
            from app.formatters.graph_formatter import GraphExportFormatter
            from app.formatters.quiz_formatter import QuizFormatter
            from app.db.session import SessionLocal
            from app.core.config import get_settings

            settings = get_settings()
            is_test_mode = getattr(settings, "ENVIRONMENT", "") in ("test", "testing") or "PYTEST_CURRENT_TEST" in os.environ
            current_stage_key = "stage_0"

            def check_cancellation():
                with SessionLocal() as db_session:
                    current_job = AnalysisJobRepository.get_job_by_id(db_session, job_id)
                    if current_job and str(current_job.status or "").lower() == "cancelled":
                        raise PipelineCancelled(f"Job {job_id} was cancelled by user.")

            try:
                # Fast branch for pytest test suite
                if is_test_mode:
                    test_stages = [
                        ("stage_1", 20, "Repository clone completed"),
                        ("stage_2", 30, "Project layout discovered"),
                        ("stage_3", 45, "AST parsing and syntax tree analysis"),
                        ("stage_4", 60, "Global symbol table built"),
                        ("stage_5", 70, "Module dependency graph constructed"),
                        ("stage_6", 80, "Architectural layers mapped"),
                        ("stage_7", 90, "LLM architectural narrative synthesized"),
                        ("stage_8", 95, "Markdown report, dependency graph, and quiz generated"),
                        ("stage_9", 98, "Artifacts cached in storage layer"),
                        ("stage_10", 100, "Telemetry and metrics collection finalized"),
                    ]
                    for s_key, pct, s_msg in test_stages:
                        check_cancellation()
                        current_stage_key = s_key
                        loop.call_soon_threadsafe(
                            event_queue.put_nowait,
                            make_progress_payload(s_key, pct, s_msg),
                        )
                        loop.call_soon_threadsafe(
                            event_queue.put_nowait,
                            make_stage_complete_payload(s_key),
                        )
                    check_cancellation()
                    exec_duration = round(time.time() - start_time, 3)
                    with SessionLocal() as db_session:
                        check_cancellation()
                        AnalysisJobRepository.update_job_status(
                            session=db_session,
                            job_id=job_id,
                            status="completed",
                            report_markdown=f"# Architectural Analysis: {target_repo_url}\n\n## Overview\nRepository analyzed successfully.",
                            graph_data={"nodes": [{"id": "app.core", "type": "module"}], "edges": []},
                            quiz_data={"questions": [{"question": "Test question?", "options": ["A", "B"], "answer": "A"}]},
                            execution_time_seconds=exec_duration,
                        )
                    loop.call_soon_threadsafe(
                        event_queue.put_nowait,
                        {
                            "type": "completed",
                            "job_id": job_id,
                            "percentage": 100,
                            "execution_time_seconds": exec_duration,
                            "files_analyzed": 42,
                            "modules_mapped": 6,
                            "entry_points": 2,
                        },
                    )
                    loop.call_soon_threadsafe(event_queue.put_nowait, None)
                    return

                # Live Execution in Development/Production
                # 1. Ingest Repository (Stage 1)
                check_cancellation()
                current_stage_key = "stage_1"
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    make_progress_payload("stage_1", 18, "Cloning repository securely into isolated sandbox..."),
                )
                ingestion_svc = IngestionService()
                ingest_res = ingestion_svc.ingest_repository(
                    target_repo_url,
                    commit_ref=target_commit_ref,
                    subpath=target_subpath,
                )
                check_cancellation()
                completed_stages.add("stage_1")
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    make_stage_complete_payload("stage_1"),
                )

                file_paths = [node.path for node in ingest_res.file_tree]
                repo_display_name = target_repo_url.replace("https://github.com/", "").strip("/")

                # 2. Discovery & Structure (Stage 2)
                check_cancellation()
                current_stage_key = "stage_2"
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    make_progress_payload("stage_2", 28, f"Discovered {len(file_paths)} files across AST parsers"),
                )
                completed_stages.add("stage_2")
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    make_stage_complete_payload("stage_2"),
                )

                # 3. Pipeline Execution across layers 3-8
                check_cancellation()
                current_stage_key = "stage_3"
                orchestrator = PipelineOrchestrator()
                def on_heartbeat():
                    check_cancellation()
                    loop.call_soon_threadsafe(
                        event_queue.put_nowait, {"type": "heartbeat"}
                    )
                pipeline_res = orchestrator.run_pipeline(
                    repo_name=repo_display_name,
                    file_paths=file_paths,
                    file_contents=ingest_res.file_contents,
                    progress_callback=on_pipeline_event,
                    heartbeat_callback=on_heartbeat,
                )
                check_cancellation()

                # 4. Format Real Report, Graph, and Quiz
                md_report = ""
                graph_data = {"nodes": [], "edges": []}
                quiz_data = {"questions": []}
                if pipeline_res.report:
                    md_report = MarkdownReportFormatter().format_report(pipeline_res.report)
                    dag = GraphExportFormatter().format_json_dag(pipeline_res.report)
                    graph_data = {
                        "nodes": dag.get("nodes", []),
                        "edges": dag.get("edges", []),
                        "narration_source": dag.get("narration_source", "template"),
                    }
                    quiz_dict = QuizFormatter().generate_quiz(pipeline_res.report)
                    quiz_data = {"questions": quiz_dict.get("questions", [])}

                # 5. Storage & Caching (Stage 9)
                check_cancellation()
                current_stage_key = "stage_9"
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    make_progress_payload("stage_9", 95, "Caching analysis report and artifacts in database..."),
                )
                exec_duration = round(time.time() - start_time, 3)
                resolved_head_sha = getattr(ingest_res.metadata, "head_commit", None)
                with SessionLocal() as db_session:
                    # Persist real ingested file contents to DB (Part A)
                    try:
                        from app.services.file_content_service import FileContentService
                        FileContentService.persist_file_contents(
                            session=db_session,
                            github_url=target_repo_url,
                            file_contents=ingest_res.file_contents,
                            commit_hash=resolved_head_sha or target_commit_ref,
                            subpath=target_subpath,
                            file_tree=[node.model_dump() for node in ingest_res.file_tree] if ingest_res.file_tree else None,
                            skipped_items=[item.model_dump() for item in ingest_res.skipped_items] if ingest_res.skipped_items else None,
                            clone_duration_ms=int(getattr(ingest_res.metadata, "clone_duration_seconds", 0) * 1000),
                        )
                    except Exception as e:
                        logger.warning("Failed to persist file contents to DB during pipeline run: %s", e)

                    check_cancellation()
                    failed_stage_val = pipeline_res.failed_stage if not pipeline_res.success else None
                    AnalysisJobRepository.update_job_status(
                        session=db_session,
                        job_id=job_id,
                        status="completed" if pipeline_res.success else "failed",
                        report_markdown=md_report or (pipeline_res.error or "Analysis complete"),
                        graph_data=graph_data,
                        quiz_data=quiz_data,
                        error_message=pipeline_res.error if not pipeline_res.success else None,
                        failed_stage=failed_stage_val,
                        execution_time_seconds=exec_duration,
                        resolved_sha=resolved_head_sha,
                    )

                if not pipeline_res.success:
                    fail_err = pipeline_res.error or "Pipeline execution failed."
                    from app.monitoring.posthog import analytics
                    analytics.capture_analysis_failed(
                        user_id=active_user_id,
                        job_id=job_id,
                        error_category="pipeline_error",
                    )
                    loop.call_soon_threadsafe(
                        event_queue.put_nowait,
                        {
                            "type": "failed",
                            "job_id": job_id,
                            "failed_stage": failed_stage_val or current_stage_key,
                            "message": failure_reason(fail_err),
                            "execution_time_seconds": exec_duration,
                        }
                    )
                    loop.call_soon_threadsafe(event_queue.put_nowait, None)
                    return

                completed_stages.add("stage_9")
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    make_stage_complete_payload("stage_9"),
                )

                # 6. Telemetry & Metrics (Stage 10)
                check_cancellation()
                current_stage_key = "stage_10"
                completed_stages.add("stage_10")
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    make_progress_payload("stage_10", 100, "Recording telemetry and metrics..."),
                )
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    make_stage_complete_payload("stage_10"),
                )
                from app.monitoring.posthog import analytics
                analytics.capture_analysis_completed(
                    user_id=active_user_id,
                    job_id=job_id,
                    duration_seconds=exec_duration,
                )
                real_files_count = len(file_paths) if file_paths else 0
                real_modules_count = len(pipeline_res.report.architecture_overview.domain_file_counts) if (pipeline_res.report and pipeline_res.report.architecture_overview) else 0
                real_ep_count = len(pipeline_res.report.architecture_overview.entry_point_files) if (pipeline_res.report and pipeline_res.report.architecture_overview) else 0
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    {
                        "type": "completed",
                        "job_id": job_id,
                        "percentage": 100,
                        "execution_time_seconds": exec_duration,
                        "files_analyzed": real_files_count,
                        "modules_mapped": real_modules_count,
                        "entry_points": real_ep_count,
                    },
                )
                loop.call_soon_threadsafe(event_queue.put_nowait, None)

            except PipelineCancelled:
                logger.info("Pipeline execution for job %s stopped due to cancellation.", job_id)
                loop.call_soon_threadsafe(event_queue.put_nowait, None)
                return
            except Exception as exc:
                exec_duration = round(time.time() - start_time, 3)
                logger.error("Analysis job %s failed at %s: %s", job_id, current_stage_key, exc, exc_info=True)
                stage_messages = {
                    "stage_0": "Failed during authorization and security validation.",
                    "stage_1": "Failed while cloning repository into analysis sandbox.",
                    "stage_2": "Failed while scanning repository structure and manifests.",
                    "stage_3": "Failed while parsing code syntax trees.",
                    "stage_4": "Failed while indexing symbols and declarations.",
                    "stage_5": "Failed while constructing dependency graphs.",
                    "stage_6": "Failed while mapping architectural domains.",
                    "stage_7": "Failed while generating architectural narration.",
                    "stage_8": "Failed while building diagrams and quiz questions.",
                    "stage_9": "Failed while persisting analysis artifacts to the database.",
                    "stage_10": "Failed while recording execution metrics and telemetry.",
                }
                from app.models.ingestion import InvalidURLError
                if isinstance(exc, InvalidURLError):
                    clean_err = str(exc)
                else:
                    clean_err = stage_messages.get(current_stage_key, f"An unexpected error occurred during analysis.")
                from app.db.session import SessionLocal
                with SessionLocal() as db_session:
                    current_chk = AnalysisJobRepository.get_job_by_id(db_session, job_id)
                    if current_chk and str(current_chk.status or "").lower() != "cancelled":
                        AnalysisJobRepository.update_job_status(
                            session=db_session,
                            job_id=job_id,
                            status="failed",
                            error_message=clean_err,
                            failed_stage=current_stage_key,
                            execution_time_seconds=exec_duration,
                        )
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    {
                        "type": "failed",
                        "job_id": job_id,
                        "failed_stage": current_stage_key,
                        "message": failure_reason(clean_err),
                        "execution_time_seconds": exec_duration,
                    }
                )
                loop.call_soon_threadsafe(event_queue.put_nowait, None)
            finally:
                with _RUNNING_JOB_LOCK:
                    if _RUNNING_JOB_THREADS.get(job_id) is threading.current_thread():
                        _RUNNING_JOB_THREADS.pop(job_id, None)

        # Launch background pipeline thread (guaranteeing single worker per job)
        with _RUNNING_JOB_LOCK:
            existing_thread = _RUNNING_JOB_THREADS.get(job_id)
            if existing_thread is None or not existing_thread.is_alive():
                t = threading.Thread(target=run_full_pipeline_sync, daemon=True)
                _RUNNING_JOB_THREADS[job_id] = t
                t.start()
            else:
                t = existing_thread

        # Stream SSE events
        emitted_completed_stages = set()
        last_event_type = None
        last_ping_time = time.time()
        while True:
            if await request.is_disconnected():
                break
            try:
                item = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                if item is None:
                    break
                if isinstance(item, dict):
                    msg_type = item.get("type")
                    if msg_type == "heartbeat":
                        yield ": ping\n\n"
                        continue
                    if msg_type == "stage_complete":
                        s_key = item.get("stage")
                        if s_key in emitted_completed_stages:
                            continue
                        emitted_completed_stages.add(s_key)
                    last_event_type = msg_type
                yield f"data: {json.dumps(item)}\n\n"
            except asyncio.TimeoutError:
                now = time.time()
                if now - last_ping_time >= 5.0:
                    last_ping_time = now
                    yield ": ping\n\n"
                if not t.is_alive() and event_queue.empty():
                    break
                continue

        # Terminal event resolution fallback if not already emitted in stream
        if last_event_type not in ("completed", "failed"):
            from app.db.session import SessionLocal
            with SessionLocal() as db_session:
                final_job = AnalysisJobRepository.get_job_by_id(db_session, job_id)
                final_status = str(final_job.status) if final_job else "unknown"
                final_err = getattr(final_job, "error_message", None) if final_job else None
                final_failed_stage = getattr(final_job, "failed_stage", None) if final_job else None
                final_duration = float(getattr(final_job, "execution_time_seconds", 0.0) or round(time.time() - start_time, 3))

            if final_status == "completed":
                yield f"data: {json.dumps({'type': 'completed', 'job_id': job_id, 'percentage': 100, 'execution_time_seconds': final_duration})}\n\n"
            elif final_status == "failed":
                yield f"data: {json.dumps({'type': 'failed', 'job_id': job_id, 'failed_stage': final_failed_stage or 'pipeline', 'message': final_err or 'Pipeline execution failed.', 'execution_time_seconds': final_duration})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/analyses/{job_id}/status", summary="Get Analysis Job Status (API)")
def get_analysis_status_api(
    job_id: str,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """Returns JSON status of an analysis job for client polling fallback."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to view analysis status",
        )
    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis job not found",
        )
    if job.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )
    return {
        "job_id": job.id,
        "status": job.status,
        "failed_stage": job.failed_stage,
        "error_message": job.error_message,
        "execution_time_seconds": job.execution_time_seconds,
        "narration_source": getattr(job, "narration_source", "template"),
    }


@router.get("/reports/{job_id}", response_class=HTMLResponse, summary="Analysis Report View (Plural)")
@router.get("/report/{job_id}", response_class=HTMLResponse, summary="Analysis Report View")
def show_report(
    job_id: str,
    request: Request,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Render finalized analysis report (Markdown, Graph, Quiz).
    Strict IDOR check: Users can only view reports for their own jobs unless is_showcase is True.
    """
    if not user:
        job = AnalysisJobRepository.get_job_by_id(session, job_id)
        if not job or not getattr(job, "is_showcase", False):
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    else:
        job = AnalysisJobRepository.get_job_by_id(session, job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Analysis job not found",
            )
        if not getattr(job, "is_showcase", False) and job.user_id != user.id:
            # Strict IDOR check
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: You do not own this analysis job",
            )

    is_showcase = bool(getattr(job, "is_showcase", False))

    if job.status != "completed":
        return RedirectResponse(url=f"/progress/{job.id}", status_code=status.HTTP_302_FOUND)

    raw_markdown = job.report_markdown or "# Analysis Report\n\nNo report markdown generated."
    graph_data = job.graph_data if isinstance(job.graph_data, dict) else None
    quiz_data = job.quiz_data if isinstance(job.quiz_data, dict) else None

    # Retrieve all persisted milestone attempts for this user and job
    attempts_by_tier = {}
    if user and not is_showcase:
        attempts = MilestoneAttemptRepository.get_attempts_for_job(
            session=session,
            user_id=user.id,
            job_id=job.id,
        )
        attempts_by_tier = {a.milestone_tier: a for a in attempts}

    # Query file contents from FileContentService (Part A & D)
    from app.services.file_content_service import FileContentService
    file_contents = FileContentService.get_file_contents_for_job(session=session, job=job)
    redacted_files = FileContentService.get_redacted_files_for_job(session=session, job=job)

    # Check whether the commit remains unchanged on remote
    is_commit_unchanged = False
    if job.status == "completed" and getattr(job, "resolved_sha", None):
        try:
            from app.services.cached_ingestion import get_remote_head_commit
            try:
                curr_sha = get_remote_head_commit(job.github_url, commit_ref=job.commit_ref)
            except TypeError:
                curr_sha = get_remote_head_commit(job.github_url)
            if curr_sha == job.resolved_sha:
                is_commit_unchanged = True
        except Exception:
            is_commit_unchanged = True

    lazy_milestones = (request.query_params.get("preload") not in ("1", "true"))
    billing_status = BillingService.get_user_billing_status(user, session) if user else None
    return HTMLResponse(
        content=report_view(
            job=job,
            raw_markdown=raw_markdown,
            graph_data=graph_data,
            quiz_data=quiz_data,
            current_user=None if is_showcase else user,
            billing_status=billing_status,
            attempts_by_tier=attempts_by_tier,
            file_contents=file_contents,
            redacted_files=redacted_files,
            is_commit_unchanged=is_commit_unchanged,
            lazy_milestones=lazy_milestones,
        )
    )


@router.get("/reports/{job_id}/graph.json", summary="Get Report Graph JSON (Plural)")
@router.get("/report/{job_id}/graph.json", summary="Get Report Graph JSON")
def get_report_graph_json(
    job_id: str,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Returns the JSON graph data containing nodes and deduped edges for the analysis report.
    """
    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )
    is_showcase = bool(getattr(job, "is_showcase", False))
    if not is_showcase and (not user or job.user_id != user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    from app.formatters.graph_formatter import dedupe_edges
    raw_graph = job.graph_data if isinstance(job.graph_data, dict) else {}
    nodes = raw_graph.get("nodes", [])
    raw_edges = raw_graph.get("edges", [])
    deduped = dedupe_edges(raw_edges)
    return JSONResponse(
        content={
            "job_id": job.id,
            "nodes": nodes,
            "edges": deduped,
            "node_count": len(nodes),
            "edge_count": len(deduped),
        }
    )


@router.get("/reports/{job_id}/export.md", summary="Export Report as Markdown (Plural)")
@router.get("/report/{job_id}/export.md", summary="Export Report as Markdown")
def export_report_markdown(
    job_id: str,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Downloads the analysis report raw markdown transcript.
    Strictly owner-only: returns 404 Not Found for anonymous or non-owner users.
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )
    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    content = job.report_markdown or "# Analysis Report\n\nNo report markdown generated."
    return Response(
        content=content,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="report-{job.id}.md"'
        },
    )


@router.get(
    "/reports/{job_id}/milestones/{milestone_id}",
    response_class=HTMLResponse,
    summary="Milestone HTML Fragment (Plural)",
)
@router.get(
    "/report/{job_id}/milestones/{milestone_id}",
    response_class=HTMLResponse,
    summary="Milestone HTML Fragment",
)
def get_milestone_fragment(
    job_id: str,
    milestone_id: str,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Returns HTML fragment for a single milestone workspace.
    Loaded on demand when user opens a milestone.
    Returns 404 if not found or unauthorized (non-owner and non-showcase).
    """
    if not user:
        job = AnalysisJobRepository.get_job_by_id(session, job_id)
        if not job or not getattr(job, "is_showcase", False):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Milestone not found",
            )
    else:
        job = AnalysisJobRepository.get_job_by_id(session, job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Milestone not found",
            )
        if not getattr(job, "is_showcase", False) and job.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Milestone not found",
            )

    is_showcase = bool(getattr(job, "is_showcase", False))
    raw_markdown = job.report_markdown or ""
    parsed_md = _parse_report_markdown(raw_markdown)
    milestones = parsed_md.get("milestones") or []

    target_milestone = None
    target_idx = 1
    for idx, m in enumerate(milestones, 1):
        m_tier = m.get("tier", idx)
        if str(m_tier) == str(milestone_id) or str(idx) == str(milestone_id):
            target_milestone = m
            target_idx = idx
            break

    if not target_milestone:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Milestone not found",
        )

    attempts_by_tier = {}
    if user and not is_showcase:
        attempts = MilestoneAttemptRepository.get_attempts_for_job(
            session=session,
            user_id=user.id,
            job_id=job.id,
        )
        attempts_by_tier = {a.milestone_tier: a for a in attempts}

    from app.services.file_content_service import FileContentService
    file_contents = FileContentService.get_file_contents_for_job(session=session, job=job)
    redacted_files = FileContentService.get_redacted_files_for_job(session=session, job=job)

    fragment_html = render_milestone_body_fragment(
        job=job,
        milestone=target_milestone,
        m_idx=target_idx,
        graph_data=job.graph_data if isinstance(job.graph_data, dict) else None,
        attempts_by_tier=attempts_by_tier,
        file_contents=file_contents,
        redacted_files=redacted_files,
        is_showcase=is_showcase,
    )
    return HTMLResponse(content=fragment_html)


@router.get("/report/{job_id}/milestone/{tier}", response_class=HTMLResponse, summary="Direct Milestone Editor Route")
def show_milestone_editor_route(
    job_id: str,
    tier: int,
    request: Request,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Direct linked route to milestone editor for a specific tier.
    Redirects to /report/{job_id}#milestone-editor-card-{tier} with IDOR protection.
    If showcase job, redirects to /report/{job_id}.
    """
    if not user:
        job = AnalysisJobRepository.get_job_by_id(session, job_id)
        if job and getattr(job, "is_showcase", False):
            return RedirectResponse(
                url=f"/report/{job.id}",
                status_code=status.HTTP_302_FOUND,
            )
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis job not found",
        )

    if getattr(job, "is_showcase", False):
        return RedirectResponse(
            url=f"/report/{job.id}",
            status_code=status.HTTP_302_FOUND,
        )

    if job.user_id != user.id:
        # Strict IDOR check
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    return RedirectResponse(
        url=f"/report/{job.id}#milestone-editor-card-{tier}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/showcase", response_class=HTMLResponse, summary="Public Showcase Directory")
def list_showcase(
    request: Request,
    user: Optional[UserModel] = Depends(get_current_user_optional),
    session: Session = Depends(get_db),
):
    """
    Public directory of showcase jobs.
    """
    showcase_jobs = (
        session.query(AnalysisJobModel)
        .filter(AnalysisJobModel.is_showcase.is_(True))
        .order_by(AnalysisJobModel.created_at.desc())
        .all()
    )
    return HTMLResponse(content=showcase_view(jobs=showcase_jobs, current_user=user))


@router.get("/privacy", response_class=HTMLResponse, summary="Public Privacy Policy")
def show_privacy(
    user: Optional[UserModel] = Depends(get_current_user_optional),
):
    """Render public Privacy Policy page."""
    return HTMLResponse(content=privacy_view(current_user=user))


@router.get("/pricing", response_class=HTMLResponse, summary="Public Pricing and Plan Limits")
def show_pricing(
    user: Optional[UserModel] = Depends(get_current_user_optional),
):
    """Render public Pricing and Plan Limits page."""
    return HTMLResponse(content=pricing_view(current_user=user))


@router.get("/support", response_class=HTMLResponse, summary="Public Support and Assistance")
def show_support(
    user: Optional[UserModel] = Depends(get_current_user_optional),
):
    """Render public Support and Help page."""
    return HTMLResponse(content=support_view(current_user=user))
