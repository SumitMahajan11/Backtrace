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
        with Session(target_engine) as session:
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

    # 4. Piston Sandbox Execution Service Check (Prompt 21)
    try:
        from app.services.piston_health import piston_health_monitor
        piston_status = piston_health_monitor.get_status()
        checks["piston_sandbox"] = piston_status
    except Exception as exc:
        checks["piston_sandbox"] = {
            "status": "unhealthy",
            "is_available": False,
            "error": str(exc),
        }

    # 5. Redis Distributed Cache & Rate Limiter Check (Prompt 28)
    redis_start = time.time()
    try:
        from app.core.config import get_settings
        settings = get_settings()
        redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
        
        # Test connection with a lightweight ping
        import redis
        client = redis.Redis.from_url(redis_url, socket_timeout=1.5, socket_connect_timeout=1.5)
        is_alive = bool(client.ping())
        redis_latency_ms = round((time.time() - redis_start) * 1000, 2)
        
        checks["redis"] = {
            "status": "healthy" if is_alive else "unhealthy",
            "latency_ms": redis_latency_ms,
            "is_connected": is_alive,
        }
    except Exception as exc:
        # In testing or when Redis is not running locally, report status accurately
        checks["redis"] = {
            "status": "unhealthy",
            "is_connected": False,
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
