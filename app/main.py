"""Main FastAPI Application Entrypoint for Backtrace Analysis Engine."""

import os
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.billing import router as billing_router
from app.api.frontend import router as frontend_router
from app.api.health import inspect_health
from app.api.pipeline import router as pipeline_router
from app.api.webhooks import router as webhooks_router
from app.core.config import get_settings
from app.db.session import init_db
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes database tables and monitoring systems on startup."""
    init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Identity, Session Management, Stripe Billing, and 11-Layer Reverse Engineering Pipeline API",
    version="1.0.0",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# CORS Configuration
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000,https://app.backtrace.dev").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    except Exception:
        pass

    logger.error(f"Unhandled server error: {exc}", exc_info=True)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred"},
    )


# Mount Routers
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(pipeline_router)
app.include_router(webhooks_router)
app.include_router(frontend_router)


@app.get("/health", tags=["Health"], summary="System Health and Readiness Inspection")
def get_health(response: Response) -> Dict[str, Any]:
    """Dynamic health check returning 200 when healthy or 503 when unhealthy."""
    payload, status_code = inspect_health()
    response.status_code = status_code
    return payload
