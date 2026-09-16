"""Health and Readiness Check Endpoint (Layer 11 Infrastructure).

Provides dynamic, real-time inspection of core pipeline dependencies:
- Database connectivity and query latency
- Layer 9 Storage / Cache operational state
- Pipeline Orchestrator readiness and parser availability
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import engine, get_db_session
from app.models.db import RepoModel
from app.orchestration.pipeline import PipelineOrchestrator


def inspect_health(target_engine=engine) -> Tuple[Dict[str, Any], int]:
    """
    Executes dynamic health check across database, storage, and orchestrator components.
    Returns (health_payload, http_status_code).
    """
    checks: Dict[str, Any] = {}
    overall_healthy = True

    # 1. Database Check
    db_start = time.time()
    try:
        with target_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_latency_ms = round((time.time() - db_start) * 1000, 2)
        checks["database"] = {
            "status": "healthy",
            "latency_ms": db_latency_ms,
        }
    except Exception as exc:
        overall_healthy = False
        checks["database"] = {
            "status": "unhealthy",
            "error": str(exc),
        }

    # 2. Storage / Cache Subsystem Check
    try:
        with get_db_session() as session:
            count = session.query(RepoModel).count()
        checks["storage_cache"] = {
            "status": "healthy",
            "tracked_repos": count,
        }
    except Exception as exc:
        overall_healthy = False
        checks["storage_cache"] = {
            "status": "unhealthy",
            "error": str(exc),
        }

    # 3. Pipeline Orchestrator Readiness Check
    try:
        orchestrator = PipelineOrchestrator()
        parser_count = len(orchestrator.parsers)
        checks["pipeline_orchestrator"] = {
            "status": "healthy" if parser_count >= 8 else "degraded",
            "registered_parsers": parser_count,
        }
        if parser_count < 8:
            overall_healthy = False
    except Exception as exc:
        overall_healthy = False
        checks["pipeline_orchestrator"] = {
            "status": "unhealthy",
            "error": str(exc),
        }

    status_str = "healthy" if overall_healthy else "unhealthy"
    status_code = 200 if overall_healthy else 503

    payload = {
        "status": status_str,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "checks": checks,
    }
    return payload, status_code
