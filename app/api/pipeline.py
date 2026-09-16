"""Pipeline Execution API Router (Protected by Auth and Gated by Billing Quota)."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.models.db import UserModel
from app.orchestration.pipeline import PipelineOrchestrator
from app.services.billing_service import BillingService

router = APIRouter(prefix="/api", tags=["Pipeline"])


class PipelineRunRequest(BaseModel):
    repo_name: str = Field(..., description="Repository name in org/repo format")
    file_paths: List[str] = Field(..., description="List of repository relative file paths")
    file_contents: Dict[str, str] = Field(..., description="Map of relative file paths to content")
    enable_rag: bool = Field(default=True, description="Whether to compute hybrid RAG embeddings")
    run_id: Optional[str] = Field(default=None, description="Optional correlated run_id for logging")


class PipelineRunResponse(BaseModel):
    success: bool
    run_id: str
    execution_time_seconds: float
    layers_executed: List[str]
    user_id: int
    user_github_username: str
    user_tier: str
    monthly_usage_count: int
    report_summary: Optional[Dict[str, Any]] = None


@router.post("/pipeline/run", response_model=PipelineRunResponse, summary="Execute 11-Layer Reverse Engineering Pipeline")
def execute_pipeline(
    payload: PipelineRunRequest,
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Triggers execution of the complete 11-layer reverse-engineering analysis pipeline.
    
    Protected endpoint: Requires a valid, unexpired JWT session access token.
    Quota-gated endpoint:
    - Paid tier: Unlimited analyses.
    - Free tier: Subject to monthly analysis quota (default: 5/month). Exceeding quota returns HTTP 402.
    """
    # 1. Quota Check & Consumption
    is_allowed, usage_count, quota_limit, tier = BillingService.check_and_consume_quota(
        user=current_user, session=session
    )

    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "quota_exceeded",
                "message": (
                    f"Free tier monthly quota exceeded ({usage_count}/{quota_limit} analyses used). "
                    "Please upgrade to Backtrace Pro for unlimited repository analyses."
                ),
                "current_usage": usage_count,
                "quota_limit": quota_limit,
                "tier": tier,
                "upgrade_url": "/billing/checkout",
            },
        )

    # 2. Pipeline Execution
    orchestrator = PipelineOrchestrator()
    result = orchestrator.run_pipeline(
        repo_name=payload.repo_name,
        file_paths=payload.file_paths,
        file_contents=payload.file_contents,
        enable_rag=payload.enable_rag,
        run_id=payload.run_id,
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline execution failed: {result.error or 'Unknown error'}",
        )

    summary = None
    if result.report:
        summary = {
            "total_files": result.report.architecture_overview.total_files,
            "milestone_count": len(result.report.milestones),
        }

    executed_layers = [e.stage.value for e in result.events] if result.events else [
        "ingestion", "parsing", "understanding", "reasoning", "synthesis", "complete"
    ]

    return PipelineRunResponse(
        success=result.success,
        run_id=result.run_id,
        execution_time_seconds=result.execution_time_seconds,
        layers_executed=executed_layers,
        user_id=current_user.id,
        user_github_username=current_user.github_username,
        user_tier=tier,
        monthly_usage_count=usage_count,
        report_summary=summary,
    )


@router.post("/analyze", response_model=PipelineRunResponse, summary="Analyze Repository (Alias)")
def analyze_repository(
    payload: PipelineRunRequest,
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Convenience alias for /api/pipeline/run, protected by user auth and quota."""
    return execute_pipeline(payload=payload, current_user=current_user, session=session)
