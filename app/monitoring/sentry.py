"""Sentry Error Monitoring Integration with Strict PII and Secret Redaction."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Set

try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
except ImportError:
    sentry_sdk = None

# Case-insensitive sensitive keys that must be redacted before transmission
SENSITIVE_KEY_PATTERNS: Set[str] = {
    "auth",
    "authorization",
    "cookie",
    "set-cookie",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "password",
    "key",
    "api_key",
    "apikey",
    "stripe_signature",
    "stripe-signature",
    "webhook_secret",
    "client_secret",
    "code",
    "cvv",
    "card",
    "card_number",
    "number",
    "exp_month",
    "exp_year",
}


def is_sensitive_key(key: str) -> bool:
    """Checks if a dictionary key contains sensitive identifiers."""
    cleaned = key.lower().replace("-", "_").strip()
    if cleaned in SENSITIVE_KEY_PATTERNS:
        return True
    for sensitive in SENSITIVE_KEY_PATTERNS:
        if sensitive in cleaned:
            return True
    return False


def scrub_sensitive_dict(data: Any) -> Any:
    """Recursively traverses and redacts sensitive keys in dictionaries or lists."""
    if isinstance(data, dict):
        scrubbed = {}
        for k, v in data.items():
            if is_sensitive_key(str(k)):
                scrubbed[k] = "[REDACTED]"
            else:
                scrubbed[k] = scrub_sensitive_dict(v)
        return scrubbed
    elif isinstance(data, list):
        return [scrub_sensitive_dict(item) for item in data]
    return data


def scrub_sentry_event(event: Dict[str, Any], hint: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Sentry before_send callback that sanitizes all incoming error events.
    Strictly strips Authorization headers, cookies, request body secrets, and user PII.
    """
    # 1. Sanitize HTTP Request Details
    if "request" in event and isinstance(event["request"], dict):
        req = event["request"]

        # Scrub Request Headers
        if "headers" in req and isinstance(req["headers"], dict):
            req["headers"] = scrub_sensitive_dict(req["headers"])

        # Scrub Request Cookies
        if "cookies" in req and isinstance(req["cookies"], dict):
            req["cookies"] = {k: "[REDACTED]" for k in req["cookies"]}

        # Scrub Query String / URL params
        if "query_string" in req and isinstance(req["query_string"], str):
            # Redact common token/code params in query strings
            req["query_string"] = re.sub(
                r"(code|token|access_token|refresh_token|secret|state)=[^&]+",
                r"\1=[REDACTED]",
                req["query_string"],
                flags=re.IGNORECASE,
            )

        # Scrub Request Body / Form / JSON payload
        if "data" in req:
            req["data"] = scrub_sensitive_dict(req["data"])

    # 2. Sanitize User Context (Zero PII Policy)
    if "user" in event and isinstance(event["user"], dict):
        user = event["user"]
        # Retain only non-PII identifier
        user_id = user.get("id") or user.get("user_id")
        event["user"] = {"id": f"usr_{user_id}" if user_id else "anonymous"}

    # 3. Sanitize Extra & Breadcrumb Contexts
    if "extra" in event and isinstance(event["extra"], dict):
        event["extra"] = scrub_sensitive_dict(event["extra"])

    if "breadcrumbs" in event and isinstance(event["breadcrumbs"], dict):
        crumbs = event["breadcrumbs"].get("values", [])
        for crumb in crumbs:
            if "data" in crumb and isinstance(crumb["data"], dict):
                crumb["data"] = scrub_sensitive_dict(crumb["data"])

    return event


def init_sentry(
    dsn: Optional[str] = None,
    environment: Optional[str] = None,
    traces_sample_rate: float = 0.1,
) -> bool:
    """
    Initializes Sentry SDK with FastAPI/Starlette integrations and scrubber hook.
    Returns True if initialized, False if DSN is missing or SDK not installed.
    """
    sentry_dsn = dsn or os.getenv("SENTRY_DSN")
    if not sentry_dsn:
        return False

    if sentry_sdk is None:
        return False

    env = environment or os.getenv("SENTRY_ENVIRONMENT", "production")

    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=env,
        traces_sample_rate=traces_sample_rate,
        before_send=scrub_sentry_event,
        send_default_pii=False,  # Explicitly disable automatic PII collection
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
    )
    return True
