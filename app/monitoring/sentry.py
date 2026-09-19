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
    "state",
}


# Safe query parameter allowlist: Only explicitly harmless navigational/pagination keys are retained
SAFE_QUERY_PARAMS: Set[str] = {
    "tag",
    "page",
    "limit",
    "sort",
    "order",
    "view",
    "filter",
    "direction",
    "tab",
    "public_filter",
}


def is_safe_query_key(key: str) -> bool:
    """Checks if a query parameter key is on the explicit harmless allowlist and not sensitive."""
    cleaned = key.lower().replace("-", "_").strip()
    return cleaned in SAFE_QUERY_PARAMS and not is_sensitive_key(cleaned)


def scrub_query_param_pairs(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Redacts all query parameters by default, preserving only safe allowlisted parameters."""
    return [
        (k, v if is_safe_query_key(k) else "[REDACTED]")
        for k, v in pairs
    ]


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


def scrub_sentry_event(event: Dict[str, Any], hint: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Sentry before_send callback that sanitizes all incoming error events and drops expected HTTP exceptions.
    Strictly strips Authorization headers, cookies, request body secrets, and user PII.
    """
    # 0. Drop handled/expected HTTPExceptions (4xx client errors and 503 graceful fallbacks)
    if hint and "exc_info" in hint and hint["exc_info"]:
        exc_type, exc_val, _ = hint["exc_info"]
        if exc_val is not None:
            from fastapi import HTTPException
            from starlette.exceptions import HTTPException as StarletteHTTPException
            if isinstance(exc_val, (HTTPException, StarletteHTTPException)):
                return None

    # 1. Sanitize HTTP Request Details
    if "request" in event and isinstance(event["request"], dict):
        req = event["request"]

        # Scrub Request Headers
        if "headers" in req and isinstance(req["headers"], dict):
            req["headers"] = scrub_sensitive_dict(req["headers"])

        # Scrub Request Cookies
        if "cookies" in req and isinstance(req["cookies"], dict):
            req["cookies"] = {k: "[REDACTED]" for k in req["cookies"]}

        # Scrub Query String / URL params (Allowlist-only policy)
        if "query_string" in req:
            qs = req["query_string"]
            if isinstance(qs, (str, bytes)):
                import urllib.parse
                qs_str = qs.decode("utf-8") if isinstance(qs, bytes) else str(qs)
                pairs = urllib.parse.parse_qsl(qs_str, keep_blank_values=True)
                scrubbed_pairs = scrub_query_param_pairs(pairs)
                req["query_string"] = urllib.parse.urlencode(scrubbed_pairs, safe="[]")

        # Scrub URL if present (Allowlist-only policy)
        if "url" in req and isinstance(req["url"], str) and "?" in req["url"]:
            import urllib.parse
            base, qs_part = req["url"].split("?", 1)
            pairs = urllib.parse.parse_qsl(qs_part, keep_blank_values=True)
            scrubbed_pairs = scrub_query_param_pairs(pairs)
            req["url"] = f"{base}?{urllib.parse.urlencode(scrubbed_pairs, safe='[]')}"

        # Scrub Request Body / Form / JSON payload
        if "data" in req:
            req["data"] = scrub_sensitive_dict(req["data"])

    # 2. Sanitize User Context (Zero PII Policy & Suppress IP Geolocation)
    if "user" in event and isinstance(event["user"], dict):
        user = event["user"]
        user_id = user.get("id") or user.get("user_id")
        event["user"] = {
            "id": f"usr_{user_id}" if user_id else "anonymous",
            "ip_address": "{{none}}",  # Suppresses Sentry IP-based geolocation resolution
        }
    else:
        event["user"] = {
            "id": "anonymous",
            "ip_address": "{{none}}",
        }

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
