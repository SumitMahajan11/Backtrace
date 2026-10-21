"""Main FastAPI Application Entrypoint for Backtrace Analysis Engine."""

import os
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.attempts import router as attempts_router
from app.api.auth import router as auth_router
from app.api.billing import router as billing_router
from app.api.frontend import router as frontend_router
from app.api.health import inspect_health
from app.api.pipeline import router as pipeline_router
from app.api.points import router as points_router
from app.api.webhooks import router as webhooks_router
from app.core.config import get_settings
from app.db.session import init_db
from app.monitoring.posthog import init_posthog
from app.monitoring.sentry import init_sentry
from app.utils.logging import get_logger

logger = get_logger("main", layer="system")
settings = get_settings()

# Initialize Sentry Error Monitoring if configured in settings
if settings.SENTRY_DSN:
    init_sentry(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
    )

# Initialize PostHog Product Analytics if configured in settings
if settings.POSTHOG_API_KEY:
    init_posthog(
        api_key=settings.POSTHOG_API_KEY,
        host=settings.POSTHOG_HOST,
    )



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes database tables and monitoring systems on startup."""
    # Clear settings cache to ensure fresh load from .env (not any stale module-level cache)
    get_settings.cache_clear()
    init_db()
    from app.services.piston_health import piston_health_monitor
    if piston_health_monitor.is_sandbox_enabled():
        piston_health_monitor.start_background_task()
    yield
    if piston_health_monitor.is_sandbox_enabled():
        piston_health_monitor.stop_background_task()


app = FastAPI(
    title=settings.APP_NAME,
    description="Identity, Session Management, Stripe Billing, and 11-Layer Reverse Engineering Pipeline API",
    version="1.0.0",
    debug=False,  # Enforce False to guarantee zero internal stack trace leakage across all environments
    lifespan=lifespan,
)

# CORS Configuration
_raw_cors = os.getenv("CORS_ALLOWED_ORIGINS") or os.getenv("CORS_ORIGINS")
if _raw_cors:
    ALLOWED_ORIGINS = [origin.strip() for origin in _raw_cors.split(",") if origin.strip()]
elif settings.CORS_ORIGINS:
    ALLOWED_ORIGINS = settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else [o.strip() for o in str(settings.CORS_ORIGINS).split(",") if o.strip()]
else:
    ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:8000",
        "https://app.backtrace.dev",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.security.headers import SecurityHeadersAndBodySizeMiddleware
app.add_middleware(SecurityHeadersAndBodySizeMiddleware)

from starlette.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.exception_handler(Exception)
async def global_unhandled_exception_handler(request: Request, exc: Exception):
    """
    Global catch-all exception handler ensuring zero internal stack trace or secret leakage.
    Dispatches to Sentry if available and returns clean, uniform HTTP 500 response.
    """
    # Let standard FastAPI HTTP exceptions pass through with their status code & detail
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    # Capture in Sentry if SDK loaded
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
        sentry_sdk.flush(timeout=3.0)
    except Exception:
        pass

    logger.error(f"Unhandled server error: {exc}", exc_info=True)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred"},
    )


# Mount Routers
app.include_router(auth_router)
app.include_router(auth_router, prefix="/api")
app.include_router(billing_router)
app.include_router(billing_router, prefix="/api")
app.include_router(pipeline_router)
app.include_router(pipeline_router, prefix="/api")
app.include_router(attempts_router)
app.include_router(attempts_router, prefix="/api")
app.include_router(points_router)
app.include_router(points_router, prefix="/api")
app.include_router(webhooks_router)
app.include_router(webhooks_router, prefix="/api")
app.include_router(frontend_router)


@app.get("/health", tags=["Health"], summary="System Health and Readiness Inspection")
def get_health(response: Response) -> Dict[str, Any]:
    """Dynamic health check returning 200 when healthy or 503 when unhealthy."""
    payload, status_code = inspect_health()
    response.status_code = status_code
    return payload


@app.get("/healthz", tags=["Health"], summary="Liveness Probe")
def get_healthz() -> Dict[str, str]:
    """Lightweight liveness probe returning 200 without database access."""
    return {"status": "ok"}


@app.get("/api/public-config", tags=["Configuration"], summary="Public System Configuration")
@app.get("/public-config", include_in_schema=False)
def get_public_config() -> Dict[str, Any]:
    """Public system configuration flag endpoint. Returns only sandbox_enabled and demo_video_url."""
    from app.services.piston_health import piston_health_monitor
    sandbox_enabled = piston_health_monitor.is_sandbox_enabled()
    demo_video_url = os.getenv("DEMO_VIDEO_URL", "")
    return {
        "sandbox_enabled": bool(sandbox_enabled),
        "demo_video_url": demo_video_url,
    }


