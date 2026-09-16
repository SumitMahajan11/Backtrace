"""API Router package initialization."""

from app.api.auth import router as auth_router
from app.api.billing import router as billing_router
from app.api.frontend import router as frontend_router
from app.api.health import inspect_health
from app.api.pipeline import router as pipeline_router
from app.api.webhooks import router as webhooks_router

__all__ = [
    "auth_router",
    "billing_router",
    "frontend_router",
    "pipeline_router",
    "webhooks_router",
    "inspect_health",
]
