"""API Router for Milestone Attempts, Structural Verification, and Piston Execution Verification Engine."""

from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.models.db import MilestoneAttemptModel, UserModel, utc_now
from app.services.execution_verifier import (
    ExecutionVerifier,
    ExecutionVerifierConnectionError,
    ExecutionVerifierError,
)
from app.services.grading_engine import GradingEngine
from app.services.hint_engine import HintEngine, HintLeakError
from app.services.points_engine import PointsEngine
from app.services.structural_verifier import StructuralVerifier, StructuralVerificationError
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.milestone_attempt_repository import MilestoneAttemptRepository
from app.ui.sanitizer import sanitize_text
from app.utils.file_filter import MAX_FILE_SIZE_BYTES

router = APIRouter(prefix="/attempts", tags=["Milestone Attempts"])
verifier = StructuralVerifier()
execution_verifier = ExecutionVerifier()
grading_engine = GradingEngine(execution_verifier=execution_verifier, structural_verifier=verifier)


class AttemptSubmissionRequest(BaseModel):
    """Payload for submitting code for structural verification."""
    submitted_code: str = Field(..., description="Raw user-submitted source code")
    language: str = Field(default="python", description="Language of the submitted code")
    mode: Optional[str] = Field(default="guess", description="Engagement mode: 'guess' or 'fill'")
    target_file: Optional[str] = Field(default=None, description="Optional target file path for multi-file milestones")
    hint_level_revealed: Optional[int] = Field(default=None, ge=0, le=2, description="Hint tier (0-2)")
    implementation_revealed: Optional[bool] = Field(default=None, description="Whether full solution was revealed")


class AttemptRunRequest(BaseModel):
    """Payload for executing code against the isolated Piston sandbox engine."""
    submitted_code: Optional[str] = Field(default=None, description="Raw user-submitted source code to execute")
    code: Optional[str] = Field(default=None, description="Alias for submitted_code")
    language: str = Field(default="python", description="Language of the submitted code")
    stdin: Optional[str] = Field(default="", description="Optional standard input stream")
    args: Optional[List[str]] = Field(default=None, description="Optional command line arguments")

    @model_validator(mode="after")
    def populate_code(self) -> "AttemptRunRequest":
        if self.submitted_code is None and self.code is not None:
            self.submitted_code = self.code
        elif self.submitted_code is None and self.code is None:
            self.submitted_code = ""
        return self


def _serialize_attempt(
    attempt: Optional[MilestoneAttemptModel],
    user_id: int,
    job_id: int,
    milestone_tier: int,
) -> Dict[str, Any]:
    """Helper ensuring consistent attempt serialization including real execution fields."""
    if attempt:
        return {
            "id": attempt.id,
            "user_id": attempt.user_id,
            "job_id": attempt.job_id,
            "milestone_tier": attempt.milestone_tier,
            "submitted_code": attempt.submitted_code,
            "status": attempt.status,
            "hint_level_revealed": attempt.hint_level_revealed,
            "implementation_revealed": attempt.implementation_revealed,
            "last_run_stdout": attempt.last_run_stdout,
            "last_run_stderr": attempt.last_run_stderr,
            "last_run_exit_code": attempt.last_run_exit_code,
            "last_run_at": attempt.last_run_at.isoformat() if attempt.last_run_at else None,
            "grading_method": attempt.grading_method,
            "grading_details": json.loads(attempt.grading_details_json) if attempt.grading_details_json else None,
            "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
            "updated_at": attempt.updated_at.isoformat() if attempt.updated_at else None,
        }
    return {
        "id": None,
        "user_id": user_id,
        "job_id": job_id,
        "milestone_tier": milestone_tier,
        "submitted_code": "",
        "status": "not_started",
        "hint_level_revealed": 0,
        "implementation_revealed": False,
        "last_run_stdout": None,
        "last_run_stderr": None,
        "last_run_exit_code": None,
        "last_run_at": None,
        "grading_method": "structural_only",
        "grading_details": None,
        "created_at": None,
        "updated_at": None,
    }


@router.get("/by-id/{attempt_id}", summary="Get Attempt By Attempt ID (IDOR Protected)")
def get_attempt_by_id(
    attempt_id: int,
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Retrieves a milestone attempt directly by primary key ID.
    Guarded by strict IDOR check (attempt.user_id must match current_user.id).
    """
    attempt = MilestoneAttemptRepository.get_attempt_by_id(session, attempt_id)
    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Milestone attempt record not found",
        )

    if attempt.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this milestone attempt",
        )

    return _serialize_attempt(attempt, attempt.user_id, attempt.job_id, attempt.milestone_tier)


@router.get("/{job_id}/{milestone_tier}", summary="Get Milestone Attempt")
def get_milestone_attempt(
    job_id: int,
    milestone_tier: int,
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Retrieves the milestone attempt, expected symbol table, and any revealed hints for the given job.
    Guarded by strict IDOR check (job must belong to authenticated user).
    """
    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")

    if job.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    attempt = MilestoneAttemptRepository.get_attempt(
        session=session,
        user_id=current_user.id,
        job_id=job_id,
        milestone_tier=milestone_tier,
    )

    expected_symbols = StructuralVerifier.extract_expected_symbols_from_graph(
        graph_data=job.graph_data,
        milestone_tier=milestone_tier,
    )

    hint_1_text: Optional[str] = None
    hint_2_text: Optional[str] = None
    reference_data: Optional[Dict[str, Any]] = None

    if attempt:
        if attempt.hint_level_revealed >= 1:
            hint_1_text = HintEngine.get_hint_1(job.graph_data, milestone_tier)
        if attempt.hint_level_revealed >= 2:
            ver_res = verifier.verify(attempt.submitted_code, expected_symbols)
            missing = ver_res.get("missing_symbols", ver_res.get("missing", []))
            hint_2_text = HintEngine.get_hint_2(job.graph_data, milestone_tier, missing_symbols=missing)
        if attempt.implementation_revealed:
            from app.services.file_content_service import FileContentService
            reference_data = FileContentService.get_milestone_reference_code(
                session=session,
                job=job,
                milestone_tier=milestone_tier,
            )

    attempt_data = _serialize_attempt(attempt, current_user.id, job_id, milestone_tier)

    return {
        "attempt": attempt_data,
        "expected_symbols": expected_symbols,
        "hint_1": hint_1_text,
        "hint_2": hint_2_text,
        "reference_implementation": reference_data,
        "confirmation_copy": {
            "hint_1": HintEngine.SELECTED_HINT_1_CONFIRM,
            "hint_2": HintEngine.CONFIRM_HINT_2_COPY,
            "reveal": HintEngine.CONFIRM_REVEAL_COPY,
        },
    }


@router.post("/{job_id}/{milestone_tier}", summary="Submit Code for Structural Verification")
def submit_milestone_attempt(
    job_id: int,
    milestone_tier: int,
    payload: AttemptSubmissionRequest,
    response: Response = None,
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Accepts user code submission, runs static structural AST verification,
    and updates the user's attempt record.
    Guarded against IDOR (job ownership) and DoS (size limit).
    """
    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")

    if job.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    # Enforce Layer 2 DoS size limit (1MB max payload)
    raw_bytes = payload.submitted_code.encode("utf-8")
    if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Submitted code size ({len(raw_bytes)} bytes) exceeds maximum limit of {MAX_FILE_SIZE_BYTES} bytes (1MB).",
        )

    # Enforce Token Bucket per-user rate limiting on code execution (Prompt 22)
    from app.security.rate_limiter import execution_rate_limiter
    rate_check = execution_rate_limiter.check_rate_limit(f"user:{current_user.id}")
    if not rate_check.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. You may execute at most {rate_check.limit} code runs per minute. Try again in {rate_check.retry_after} seconds.",
            headers={
                "Retry-After": str(rate_check.retry_after),
                "X-RateLimit-Limit": str(rate_check.limit),
                "X-RateLimit-Remaining": str(rate_check.remaining),
                "X-RateLimit-Reset": str(rate_check.reset_seconds),
            },
        )

    if response is not None:
        response.headers["X-RateLimit-Limit"] = str(rate_check.limit)
        response.headers["X-RateLimit-Remaining"] = str(rate_check.remaining)
        response.headers["X-RateLimit-Reset"] = str(rate_check.reset_seconds)

    # Extract expected symbol table from the milestone's analysis data
    expected_symbols = StructuralVerifier.extract_expected_symbols_from_graph(
        graph_data=job.graph_data,
        milestone_tier=milestone_tier,
    )

    # Execute Tiered Grading Engine (Prompt 17 & 25)
    try:
        grading_result = grading_engine.grade_attempt(
            job=job,
            milestone_tier=milestone_tier,
            submitted_code=payload.submitted_code,
            language=payload.language,
            graph_data=job.graph_data,
            mode=payload.mode or "guess",
            target_file=payload.target_file,
            session=session,
        )
    except StructuralVerificationError as e:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(e),
        )
    except ExecutionVerifierConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e) or "Code execution sandbox is currently unavailable. Please try again shortly.",
        )

    new_status = grading_result["status"]
    verification_result = grading_result.get("verification", {})
    exec_result = grading_result.get("execution", {})
    grading_method = grading_result.get("grading_method", "structural_only")
    grading_details = grading_result.get("details", {})

    attempt = MilestoneAttemptRepository.save_or_update_attempt(
        session=session,
        user_id=current_user.id,
        job_id=job_id,
        milestone_tier=milestone_tier,
        submitted_code=payload.submitted_code,
        status=new_status,
        hint_level_revealed=payload.hint_level_revealed,
        implementation_revealed=payload.implementation_revealed,
        last_run_stdout=exec_result.get("stdout", ""),
        last_run_stderr=exec_result.get("stderr", ""),
        last_run_exit_code=exec_result.get("exit_code"),
        last_run_at=utc_now(),
        grading_method=grading_method,
        grading_details_json=json.dumps(grading_details) if grading_details else None,
    )

    # Server-side Points Award Engine Hook (Prompt 23)
    points_award_data = None
    if new_status == "structurally_verified":
        award_res = PointsEngine.award_points_for_milestone(
            session=session,
            user_id=current_user.id,
            job=job,
            milestone_tier=milestone_tier,
            attempt=attempt,
        )
        points_award_data = award_res.to_dict()

    return {
        "attempt": _serialize_attempt(attempt, current_user.id, job_id, milestone_tier),
        "verification": verification_result,
        "execution": exec_result,
        "grading_method": grading_method,
        "grading_details": grading_details,
        "points_award": points_award_data,
    }


@router.post("/{job_id}/{milestone_tier}/run", summary="Run Code in Isolated Piston Sandbox")
def run_milestone_code(
    job_id: int,
    milestone_tier: int,
    payload: AttemptRunRequest,
    response: Response = None,
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Executes submitted code against self-hosted Piston isolated sandbox.
    Returns real stdout, stderr, exit code, and execution time.
    Persists last_run_* state on MilestoneAttemptModel separate from graded Submit fields.
    Guarded by strict IDOR check (job ownership) and DoS size limits.
    """
    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")

    if job.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    # Enforce Layer 2 DoS size limit (1MB max payload)
    raw_bytes = payload.submitted_code.encode("utf-8")
    if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Submitted code size ({len(raw_bytes)} bytes) exceeds maximum limit of {MAX_FILE_SIZE_BYTES} bytes (1MB).",
        )

    # Enforce Token Bucket per-user rate limiting on code execution (Prompt 22)
    from app.security.rate_limiter import execution_rate_limiter
    rate_check = execution_rate_limiter.check_rate_limit(f"user:{current_user.id}")
    if not rate_check.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. You may execute at most {rate_check.limit} code runs per minute. Try again in {rate_check.retry_after} seconds.",
            headers={
                "Retry-After": str(rate_check.retry_after),
                "X-RateLimit-Limit": str(rate_check.limit),
                "X-RateLimit-Remaining": str(rate_check.remaining),
                "X-RateLimit-Reset": str(rate_check.reset_seconds),
            },
        )

    if response is not None:
        response.headers["X-RateLimit-Limit"] = str(rate_check.limit)
        response.headers["X-RateLimit-Remaining"] = str(rate_check.remaining)
        response.headers["X-RateLimit-Reset"] = str(rate_check.reset_seconds)

    # Execute against Piston sandbox
    try:
        exec_result = execution_verifier.execute(
            submitted_code=payload.submitted_code,
            language=payload.language,
            stdin=payload.stdin or "",
            args=payload.args or [],
        )
    except ExecutionVerifierConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e) or "Code execution sandbox is currently unavailable. Please try again shortly.",
        )
    except ExecutionVerifierError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution verification failed: {e}",
        )

    # Record real execution run on database attempt record
    attempt = MilestoneAttemptRepository.record_run_result(
        session=session,
        user_id=current_user.id,
        job_id=job_id,
        milestone_tier=milestone_tier,
        submitted_code=payload.submitted_code,
        stdout=exec_result.get("stdout", ""),
        stderr=exec_result.get("stderr", ""),
        exit_code=exec_result.get("exit_code"),
    )

    return {
        "attempt": _serialize_attempt(attempt, current_user.id, job_id, milestone_tier),
        "execution": exec_result,
    }


@router.post("/{job_id}/{milestone_tier}/hint", summary="Request Progressive Tiered Hint")
def request_milestone_hint(
    job_id: int,
    milestone_tier: int,
    mode: Optional[str] = Query(default=None),
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Progressively unlocks Hint 1 or Hint 2 for an active milestone attempt.
    Enforces 'try first' rule (locked on untouched milestones in guess mode; immediate in fill mode).
    Guarded by strict IDOR check.
    """
    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")

    if job.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    attempt = MilestoneAttemptRepository.get_attempt(
        session=session,
        user_id=current_user.id,
        job_id=job_id,
        milestone_tier=milestone_tier,
    )

    current_level = (attempt.hint_level_revealed if attempt else 0) or 0
    next_level = min(2, current_level + 1) if current_level < 2 else 2

    # Gated rule: Hint 2 and beyond require having made a first implementation attempt (submitting code), unless fill mode
    if next_level >= 2 and mode != "fill":
        if not attempt or not attempt.submitted_code or attempt.status == "not_started":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Hint 2 is locked until you make your first implementation attempt. Try writing and submitting code first!",
            )

    # Initialize attempt if not present (e.g. user requesting Hint 1 on a fresh milestone)
    if not attempt:
        attempt = MilestoneAttemptRepository.save_or_update_attempt(
            session=session,
            user_id=current_user.id,
            job_id=job_id,
            milestone_tier=milestone_tier,
            submitted_code="",
            status="attempting" if mode == "fill" else "not_started",
            hint_level_revealed=0,
        )

    hint_1 = HintEngine.get_hint_1(job.graph_data, milestone_tier)
    hint_2 = None

    if next_level >= 2:
        expected_symbols = StructuralVerifier.extract_expected_symbols_from_graph(
            graph_data=job.graph_data,
            milestone_tier=milestone_tier,
        )
        ver_res = verifier.verify(attempt.submitted_code or "", expected_symbols)
        missing = ver_res.get("missing_symbols", ver_res.get("missing", []))
        hint_2 = HintEngine.get_hint_2(job.graph_data, milestone_tier, missing_symbols=missing)

    updated_attempt = MilestoneAttemptRepository.save_or_update_attempt(
        session=session,
        user_id=current_user.id,
        job_id=job_id,
        milestone_tier=milestone_tier,
        submitted_code=attempt.submitted_code,
        status=attempt.status,
        hint_level_revealed=next_level,
        implementation_revealed=attempt.implementation_revealed,
    )

    return {
        "milestone_tier": milestone_tier,
        "hint_level_revealed": updated_attempt.hint_level_revealed,
        "hint_1": hint_1,
        "hint_2": hint_2,
        "active_hint": hint_2 if next_level == 2 else hint_1,
        "next_confirm_copy": HintEngine.CONFIRM_HINT_2_COPY if next_level == 1 else None,
    }


@router.post("/{job_id}/{milestone_tier}/reveal", summary="Reveal Reference Implementation")
def reveal_milestone_implementation(
    job_id: int,
    milestone_tier: int,
    mode: Optional[str] = Query(default=None),
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Explicitly reveals the reference structural skeleton implementation.
    Gated behind its own confirmation. Follows strict per-user IDOR protection.
    """
    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")

    if job.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    attempt = MilestoneAttemptRepository.get_attempt(
        session=session,
        user_id=current_user.id,
        job_id=job_id,
        milestone_tier=milestone_tier,
    )

    if not attempt or attempt.status == "not_started":
        if mode == "fill":
            attempt = MilestoneAttemptRepository.save_or_update_attempt(
                session=session,
                user_id=current_user.id,
                job_id=job_id,
                milestone_tier=milestone_tier,
                submitted_code="",
                status="attempting",
                hint_level_revealed=0,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reference implementation is locked until you start this milestone. Try writing code first!",
            )

    updated_attempt = MilestoneAttemptRepository.save_or_update_attempt(
        session=session,
        user_id=current_user.id,
        job_id=job_id,
        milestone_tier=milestone_tier,
        submitted_code=attempt.submitted_code,
        status=attempt.status,
        hint_level_revealed=attempt.hint_level_revealed,
        implementation_revealed=True,
    )

    from app.services.file_content_service import FileContentService
    ref_data = FileContentService.get_milestone_reference_code(
        session=session,
        job=job,
        milestone_tier=milestone_tier,
    )

    return {
        "milestone_tier": milestone_tier,
        "implementation_revealed": updated_attempt.implementation_revealed,
        "hint_level_revealed": updated_attempt.hint_level_revealed,
        "reference_implementation": ref_data,
    }


@router.get("/{job_id}/{milestone_tier}/view", response_class=HTMLResponse, summary="View Attempt Code (XSS Sanitized)")
def view_attempt_rendered(
    job_id: int,
    milestone_tier: int,
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> HTMLResponse:
    """
    Renders the submitted code back as safely escaped HTML text.
    Strictly prevents Stored XSS attacks.
    """
    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")

    if job.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    attempt = MilestoneAttemptRepository.get_attempt(
        session=session,
        user_id=current_user.id,
        job_id=job_id,
        milestone_tier=milestone_tier,
    )

    raw_code = attempt.submitted_code if attempt else ""
    escaped_code = html.escape(raw_code)

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Milestone {milestone_tier} Attempt</title></head>
    <body style="font-family: monospace; padding: 2rem; background: #121212; color: #fff;">
        <h2>Milestone {milestone_tier} Submission Code</h2>
        <div id="status">Status: {html.escape(attempt.status if attempt else 'not_started')}</div>
        <pre><code id="submitted-code">{escaped_code}</code></pre>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@router.post("/{job_id}/{milestone_tier}/review", summary="Mark Milestone as Reviewed ('Just Read It' Mode)")
def mark_milestone_reviewed(
    job_id: int,
    milestone_tier: int,
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Marks milestone as reviewed and completed without code grading or AST checks.
    Uses existing 'structurally_verified' milestone status and 'reviewed' grading method.
    Guarded by strict IDOR check (job ownership).
    """
    job = AnalysisJobRepository.get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")

    if job.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not own this analysis job",
        )

    attempt = MilestoneAttemptRepository.get_attempt(
        session=session,
        user_id=current_user.id,
        job_id=job_id,
        milestone_tier=milestone_tier,
    )

    submitted_code = attempt.submitted_code if attempt else ""
    hint_level = attempt.hint_level_revealed if attempt else 0
    impl_revealed = attempt.implementation_revealed if attempt else False

    updated_attempt = MilestoneAttemptRepository.save_or_update_attempt(
        session=session,
        user_id=current_user.id,
        job_id=job_id,
        milestone_tier=milestone_tier,
        submitted_code=submitted_code,
        status="structurally_verified",
        hint_level_revealed=hint_level,
        implementation_revealed=impl_revealed,
        grading_method="reviewed",
        last_run_at=utc_now(),
    )

    return {
        "status": "structurally_verified",
        "grading_method": "reviewed",
        "attempt": _serialize_attempt(updated_attempt, current_user.id, job_id, milestone_tier),
    }

