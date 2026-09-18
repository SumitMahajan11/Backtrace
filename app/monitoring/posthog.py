"""PostHog Product Analytics Client with Strict PII and Bounded Property Discipline."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Union

try:
    from posthog import Posthog
except ImportError:
    Posthog = None


class AnalyticsService:
    """
    Centralized analytics service for tracking product funnels and lifecycle events.
    Enforces strict PII anonymization (distinct_id=usr_{user_id}) and bounded event properties.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        host: Optional[str] = None,
        disabled: bool = False,
    ):
        from app.core.config import get_settings
        settings = get_settings()

        self.api_key = api_key or os.getenv("POSTHOG_API_KEY") or settings.POSTHOG_API_KEY or ""
        self.host = host or os.getenv("POSTHOG_HOST") or settings.POSTHOG_HOST or "https://app.posthog.com"
        self.disabled = disabled or os.getenv("ANALYTICS_DISABLED", "false").lower() in ("true", "1")
        self._captured_events: List[Dict[str, Any]] = []

        self._client: Optional[Any] = None
        if not self.disabled and self.api_key and Posthog is not None:
            self._client = Posthog(
                project_api_key=self.api_key,
                host=self.host,
            )

    def flush(self) -> None:
        """Flushes queued events to PostHog server."""
        if self._client and not self.disabled:
            try:
                self._client.flush()
            except Exception:
                pass

    def _get_distinct_id(self, user_id: Union[int, str]) -> str:
        """Formats clean, non-PII user identifier."""
        return f"usr_{user_id}"

    def capture(
        self,
        event_name: str,
        user_id: Union[int, str],
        properties: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Captures an analytics event with strict PII validation.
        Records to in-memory buffer and forwards to PostHog client if initialized.
        """
        distinct_id = self._get_distinct_id(user_id)
        props = properties.copy() if properties else {}

        # Strip any accidental PII keys before recording
        forbidden_pii = {"email", "username", "password", "token", "file_contents", "raw_files", "card", "secret"}
        safe_properties = {
            k: v for k, v in props.items()
            if k.lower() not in forbidden_pii
        }

        event_payload = {
            "event": event_name,
            "distinct_id": distinct_id,
            "properties": safe_properties,
        }

        self._captured_events.append(event_payload)

        if self._client and not self.disabled:
            try:
                self._client.capture(
                    distinct_id=distinct_id,
                    event=event_name,
                    properties=safe_properties,
                )
            except Exception:
                pass  # Avoid crashing application on analytics transmission error

        return event_payload

    # -------------------------------------------------------------------------
    # 6 Explicit Mandatory Lifecycle Events
    # -------------------------------------------------------------------------

    def capture_user_signup(self, user_id: Union[int, str], is_admin: bool = False) -> Dict[str, Any]:
        """Track new user account creation via GitHub OAuth."""
        return self.capture(
            event_name="user_signup",
            user_id=user_id,
            properties={
                "auth_provider": "github",
                "is_admin": is_admin,
            },
        )

    def capture_analysis_submitted(
        self,
        user_id: Union[int, str],
        job_id: Union[int, str],
        tier: str = "free",
    ) -> Dict[str, Any]:
        """Track when a repository analysis is started."""
        return self.capture(
            event_name="analysis_submitted",
            user_id=user_id,
            properties={
                "job_id": str(job_id),
                "tier": tier,
                "repo_host": "github.com",
            },
        )

    def capture_analysis_completed(
        self,
        user_id: Union[int, str],
        job_id: Union[int, str],
        duration_seconds: float,
        tier: str = "free",
    ) -> Dict[str, Any]:
        """Track successful 11-layer pipeline completion."""
        return self.capture(
            event_name="analysis_completed",
            user_id=user_id,
            properties={
                "job_id": str(job_id),
                "tier": tier,
                "duration_seconds": round(duration_seconds, 2),
                "status": "completed",
            },
        )

    def capture_analysis_failed(
        self,
        user_id: Union[int, str],
        job_id: Union[int, str],
        error_category: str = "pipeline_error",
        tier: str = "free",
    ) -> Dict[str, Any]:
        """Track pipeline analysis failure with a low-cardinality category."""
        return self.capture(
            event_name="analysis_failed",
            user_id=user_id,
            properties={
                "job_id": str(job_id),
                "tier": tier,
                "error_category": error_category,
                "status": "failed",
            },
        )

    def capture_subscription_started(
        self,
        user_id: Union[int, str],
        tier: str = "paid",
        plan: str = "monthly",
    ) -> Dict[str, Any]:
        """Track successful Stripe subscription checkout."""
        return self.capture(
            event_name="subscription_started",
            user_id=user_id,
            properties={
                "tier": tier,
                "plan": plan,
                "payment_provider": "stripe",
            },
        )

    def capture_subscription_cancelled(
        self,
        user_id: Union[int, str],
        reason: str = "user_cancelled",
    ) -> Dict[str, Any]:
        """Track Stripe subscription cancellation."""
        return self.capture(
            event_name="subscription_cancelled",
            user_id=user_id,
            properties={
                "tier": "free",
                "cancellation_reason": reason,
                "payment_provider": "stripe",
            },
        )

    def get_captured_events(self) -> List[Dict[str, Any]]:
        """Returns in-memory captured events (primarily for testing and auditing)."""
        return list(self._captured_events)

    def clear_captured_events(self) -> None:
        """Clears in-memory captured events buffer."""
        self._captured_events.clear()


# Global singleton instance for easy import across services and handlers
analytics = AnalyticsService()


def init_posthog(
    api_key: Optional[str] = None,
    host: Optional[str] = None,
    disabled: bool = False,
) -> AnalyticsService:
    """Explicitly initializes or re-configures the global PostHog analytics singleton."""
    global analytics
    analytics = AnalyticsService(api_key=api_key, host=host, disabled=disabled)
    return analytics

