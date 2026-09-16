"""Billing and Subscription Service integrating Stripe Hosted Checkout and Customer Portal."""

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import stripe
from sqlalchemy.orm import Session

from app.models.db import SubscriptionModel, UserModel, utc_now
from app.storage.billing_repository import BillingRepository

# Stripe & Quota Configuration
STRIPE_API_KEY: str = os.getenv("STRIPE_API_KEY", "")
STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID: str = os.getenv("STRIPE_PRICE_ID", "price_backtrace_pro_monthly")
FREE_TIER_MONTHLY_QUOTA: int = int(os.getenv("FREE_TIER_MONTHLY_QUOTA", "5"))

DEFAULT_SUCCESS_URL: str = os.getenv(
    "STRIPE_SUCCESS_URL", "http://localhost:3000/billing/success?session_id={CHECKOUT_SESSION_ID}"
)
DEFAULT_CANCEL_URL: str = os.getenv("STRIPE_CANCEL_URL", "http://localhost:3000/billing/canceled")
DEFAULT_PORTAL_RETURN_URL: str = os.getenv("STRIPE_PORTAL_RETURN_URL", "http://localhost:3000/billing")

if STRIPE_API_KEY:
    stripe.api_key = STRIPE_API_KEY


class BillingServiceError(Exception):
    """Exception raised for billing or quota-related failures."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class BillingService:
    """Orchestrates Stripe Checkout, Customer Portal, Webhook verification, and Quota Gating."""

    @staticmethod
    def get_quota_limit() -> int:
        """Retrieves dynamically configured monthly quota for free-tier users."""
        return int(os.getenv("FREE_TIER_MONTHLY_QUOTA", str(FREE_TIER_MONTHLY_QUOTA)))

    @classmethod
    def create_checkout_session(
        cls,
        user: UserModel,
        session: Session,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        price_id: Optional[str] = None,
    ) -> str:
        """
        Creates a hosted Stripe Checkout Session for upgrading to the Paid tier.
        Zero PCI scope: Raw credit card data never touches Backtrace application code.
        """
        if not stripe.api_key and STRIPE_API_KEY:
            stripe.api_key = STRIPE_API_KEY

        p_id = price_id or os.getenv("STRIPE_PRICE_ID", STRIPE_PRICE_ID)
        s_url = success_url or DEFAULT_SUCCESS_URL
        c_url = cancel_url or DEFAULT_CANCEL_URL

        # Derive customer ID strictly from authenticated user's database record
        sub = BillingRepository.get_subscription_by_user_id(session, user.id)
        existing_customer_id = sub.stripe_customer_id if sub else None

        checkout_kwargs: Dict[str, Any] = {
            "mode": "subscription",
            "payment_method_types": ["card"],
            "line_items": [
                {
                    "price": p_id,
                    "quantity": 1,
                }
            ],
            "client_reference_id": str(user.id),
            "success_url": s_url,
            "cancel_url": c_url,
            "metadata": {
                "user_id": str(user.id),
                "github_username": user.github_username,
            },
        }

        if existing_customer_id:
            checkout_kwargs["customer"] = existing_customer_id
        elif user.email:
            checkout_kwargs["customer_email"] = user.email

        try:
            checkout_session = stripe.checkout.Session.create(**checkout_kwargs)
            return checkout_session.url
        except Exception as exc:
            raise BillingServiceError(f"Stripe Checkout error: {exc}", status_code=502)

    @classmethod
    def create_customer_portal_session(
        cls,
        user: UserModel,
        session: Session,
        return_url: Optional[str] = None,
    ) -> str:
        """
        Creates a hosted Stripe Customer Portal Session for subscription management.
        Guarantees users can only access their own customer portal.
        """
        if not stripe.api_key and STRIPE_API_KEY:
            stripe.api_key = STRIPE_API_KEY

        sub = BillingRepository.get_subscription_by_user_id(session, user.id)
        if not sub or not sub.stripe_customer_id:
            raise BillingServiceError(
                "No active Stripe customer record found for this user account. Please subscribe first.",
                status_code=400,
            )

        r_url = return_url or DEFAULT_PORTAL_RETURN_URL

        try:
            portal_session = stripe.billing_portal.Session.create(
                customer=sub.stripe_customer_id,
                return_url=r_url,
            )
            return portal_session.url
        except Exception as exc:
            raise BillingServiceError(f"Stripe Customer Portal error: {exc}", status_code=502)

    @classmethod
    def verify_and_construct_webhook_event(
        cls,
        payload_bytes: bytes,
        sig_header: Optional[str],
        webhook_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Verifies the cryptographic HMAC-SHA256 signature on incoming Stripe webhooks.
        Rejects spoofed requests missing or failing signature verification.
        """
        secret = webhook_secret or os.getenv("STRIPE_WEBHOOK_SECRET", STRIPE_WEBHOOK_SECRET)
        if not sig_header:
            raise BillingServiceError("Missing Stripe-Signature header", status_code=400)

        if not secret:
            raise BillingServiceError("Stripe webhook signing secret is not configured", status_code=500)

        try:
            event = stripe.Webhook.construct_event(
                payload=payload_bytes,
                sig_header=sig_header,
                secret=secret,
            )
            return event
        except stripe.error.SignatureVerificationError as exc:
            raise BillingServiceError(f"Invalid Stripe webhook signature: {exc}", status_code=400)
        except ValueError as exc:
            raise BillingServiceError(f"Invalid JSON webhook payload: {exc}", status_code=400)
        except Exception as exc:
            raise BillingServiceError(f"Webhook construction failed: {exc}", status_code=400)

    @classmethod
    def process_webhook_event(
        cls,
        event: Any,
        session: Session,
    ) -> Dict[str, Any]:
        """
        Idempotently processes verified Stripe webhook events using event ID deduplication.
        Handles checkout.session.completed, customer.subscription.updated, and customer.subscription.deleted.
        """
        if hasattr(event, "to_dict"):
            event_dict = event.to_dict()
        elif isinstance(event, dict):
            event_dict = event
        else:
            event_dict = dict(event)

        event_id = event_dict.get("id")
        event_type = event_dict.get("type", "")

        if not event_id:
            raise BillingServiceError("Webhook event missing required 'id' attribute", status_code=400)

        # Idempotency Check: Ignore duplicate events
        if BillingRepository.is_webhook_event_processed(session, event_id):
            return {
                "status": "ignored",
                "message": "Event has already been processed (idempotent duplicate)",
                "event_id": event_id,
                "event_type": event_type,
            }

        data_object = event_dict.get("data", {}).get("object", {})

        if event_type == "checkout.session.completed":
            cls._handle_checkout_session_completed(data_object, session)
        elif event_type == "customer.subscription.updated":
            cls._handle_subscription_updated(data_object, session)
        elif event_type == "customer.subscription.deleted":
            cls._handle_subscription_deleted(data_object, session)

        # Record event in deduplication table
        BillingRepository.record_processed_webhook_event(session, event_id, event_type)

        return {
            "status": "processed",
            "event_id": event_id,
            "event_type": event_type,
        }

    @classmethod
    def _handle_checkout_session_completed(cls, obj: Dict[str, Any], session: Session) -> None:
        """Links customer ID and subscription ID to the user after successful checkout."""
        client_ref = obj.get("client_reference_id")
        user_id_str = client_ref or obj.get("metadata", {}).get("user_id")

        if not user_id_str:
            return

        try:
            user_id = int(user_id_str)
        except (ValueError, TypeError):
            return

        stripe_customer_id = obj.get("customer")
        stripe_subscription_id = obj.get("subscription")

        if not stripe_customer_id:
            return

        BillingRepository.upsert_subscription(
            session=session,
            user_id=user_id,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            status="active",
        )

        from app.monitoring.posthog import analytics
        analytics.capture_subscription_started(user_id=user_id, tier="paid", plan="monthly")

    @classmethod
    def _handle_subscription_updated(cls, obj: Dict[str, Any], session: Session) -> None:
        """Updates subscription status and current_period_end."""
        sub_id = obj.get("id")
        status_str = obj.get("status", "active")
        period_end_ts = obj.get("current_period_end")

        period_end_dt = None
        if period_end_ts:
            try:
                period_end_dt = datetime.fromtimestamp(period_end_ts, timezone.utc).replace(tzinfo=None)
            except Exception:
                pass

        if sub_id:
            BillingRepository.update_subscription_status(
                session=session,
                stripe_subscription_id=sub_id,
                status=status_str,
                current_period_end=period_end_dt,
            )

    @classmethod
    def _handle_subscription_deleted(cls, obj: Dict[str, Any], session: Session) -> None:
        """Marks subscription as canceled upon deletion in Stripe."""
        sub_id = obj.get("id")
        if sub_id:
            sub = BillingRepository.get_subscription_by_stripe_subscription_id(session, sub_id)
            BillingRepository.update_subscription_status(
                session=session,
                stripe_subscription_id=sub_id,
                status="canceled",
            )
            if sub:
                from app.monitoring.posthog import analytics
                analytics.capture_subscription_cancelled(user_id=sub.user_id, reason="stripe_subscription_deleted")

    @classmethod
    def get_user_billing_status(cls, user: UserModel, session: Session) -> Dict[str, Any]:
        """Returns the user's tier, quota consumption, and subscription status."""
        sub = BillingRepository.get_subscription_by_user_id(session, user.id)
        now = utc_now()
        is_paid = (
            sub is not None
            and sub.status in ("active", "trialing")
            and (sub.current_period_end is None or sub.current_period_end > now)
        )

        current_usage = BillingRepository.get_monthly_usage_count(session, user.id)
        quota_limit = None if is_paid else cls.get_quota_limit()

        return {
            "user_id": user.id,
            "tier": "paid" if is_paid else "free",
            "subscription_status": sub.status if sub else "inactive",
            "monthly_usage": current_usage,
            "monthly_quota": quota_limit,
            "is_quota_exceeded": False if is_paid else (current_usage >= cls.get_quota_limit()),
            "current_period_end": sub.current_period_end.isoformat() if sub and sub.current_period_end else None,
        }

    @classmethod
    def check_and_consume_quota(
        cls,
        user: UserModel,
        session: Session,
    ) -> Tuple[bool, int, int, str]:
        """
        Concurrency-safe quota check and consumption for analysis pipeline execution.
        
        Returns:
            (is_allowed: bool, current_usage: int, quota_limit: int, tier: str)
            
        - Paid users: Bypass quota checks, record usage event, and return is_allowed=True.
        - Free users: If monthly_usage >= quota, returns is_allowed=False without recording.
                      If monthly_usage < quota, records usage event and returns is_allowed=True.
        """
        sub = BillingRepository.get_subscription_by_user_id(session, user.id)
        now = utc_now()
        is_paid = (
            sub is not None
            and sub.status in ("active", "trialing")
            and (sub.current_period_end is None or sub.current_period_end > now)
        )

        quota_limit = cls.get_quota_limit()

        if is_paid:
            BillingRepository.record_usage_event(session, user.id, event_type="repo_analysis")
            current_usage = BillingRepository.get_monthly_usage_count(session, user.id)
            return True, current_usage, -1, "paid"

        # Free Tier Quota Check
        current_usage = BillingRepository.get_monthly_usage_count(session, user.id)
        if current_usage >= quota_limit:
            return False, current_usage, quota_limit, "free"

        # Consume quota by recording usage event
        BillingRepository.record_usage_event(session, user.id, event_type="repo_analysis")
        session.flush()
        new_usage = BillingRepository.get_monthly_usage_count(session, user.id)
        return True, new_usage, quota_limit, "free"
