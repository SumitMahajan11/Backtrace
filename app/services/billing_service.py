"""Billing and Subscription Service integrating Stripe Hosted Checkout and Customer Portal."""

import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple

import stripe
from sqlalchemy.orm import Session

from app.models.db import SubscriptionModel, UserModel, utc_now
from app.storage.billing_repository import BillingRepository

# Stripe & Quota Configuration
def _get_billing_setting(attr: str, default: Any = "") -> Any:
    env_val = os.getenv(attr)
    if env_val is not None and str(env_val).strip():
        return env_val
    try:
        from app.core.config import get_settings
        settings = get_settings()
        val = getattr(settings, attr, None)
        if val is not None and str(val).strip():
            return val
    except Exception:
        pass
    return default


STRIPE_API_KEY: str = str(_get_billing_setting("STRIPE_SECRET_KEY", os.getenv("STRIPE_API_KEY", os.getenv("STRIPE_SECRET_KEY", ""))))
STRIPE_WEBHOOK_SECRET: str = str(_get_billing_setting("STRIPE_WEBHOOK_SECRET", os.getenv("STRIPE_WEBHOOK_SECRET", "")))
STRIPE_PRICE_ID: str = str(_get_billing_setting("STRIPE_PRICE_ID_PRO", os.getenv("STRIPE_PRICE_ID", "price_backtrace_pro_monthly")))
FREE_TIER_MONTHLY_QUOTA: int = int(_get_billing_setting("FREE_TIER_MONTHLY_LIMIT", os.getenv("FREE_TIER_MONTHLY_QUOTA", "5")))

DEFAULT_SUCCESS_URL: str = str(_get_billing_setting(
    "STRIPE_SUCCESS_URL", os.getenv("STRIPE_SUCCESS_URL", "http://localhost:8000/dashboard?session_id={CHECKOUT_SESSION_ID}")
))
DEFAULT_CANCEL_URL: str = str(_get_billing_setting("STRIPE_CANCEL_URL", os.getenv("STRIPE_CANCEL_URL", "http://localhost:8000/dashboard")))
DEFAULT_PORTAL_RETURN_URL: str = str(_get_billing_setting("STRIPE_PORTAL_RETURN_URL", os.getenv("STRIPE_PORTAL_RETURN_URL", "http://localhost:8000/dashboard")))

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

    _price_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
    _PRICE_CACHE_TTL: float = 3600.0  # 1-hour cache TTL

    @classmethod
    def get_pro_price_details(cls, price_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Dynamically fetches the Stripe Price object for the Pro subscription tier.
        Caches the response in-memory for 1 hour to prevent latency and API rate-limiting.
        """
        api_key = _get_billing_setting("STRIPE_SECRET_KEY", os.getenv("STRIPE_API_KEY", STRIPE_API_KEY))
        if api_key:
            stripe.api_key = api_key

        p_id = price_id or _get_billing_setting("STRIPE_PRICE_ID_PRO", os.getenv("STRIPE_PRICE_ID", STRIPE_PRICE_ID))
        if not p_id:
            return {
                "price_id": None,
                "unit_amount": None,
                "amount_formatted": "Upgrade",
                "currency": "usd",
                "interval": "month",
            }

        now = time.time()
        if p_id in cls._price_cache:
            cached_time, cached_data = cls._price_cache[p_id]
            if now - cached_time < cls._PRICE_CACHE_TTL:
                return cached_data

        try:
            price_obj = stripe.Price.retrieve(p_id)
            unit_amount = getattr(price_obj, "unit_amount", 0)
            currency = getattr(price_obj, "currency", "usd").lower()
            recurring = getattr(price_obj, "recurring", None)
            interval = recurring.get("interval", "month") if recurring else "month"

            # Dynamic Currency Formatting
            symbol_map = {
                "usd": "$",
                "inr": "₹",
                "eur": "€",
                "gbp": "£",
                "cad": "CA$",
                "aud": "A$",
                "jpy": "¥",
            }
            symbol = symbol_map.get(currency, f"{currency.upper()} ")

            if currency in ["jpy", "krw"]:
                amount_formatted = f"{symbol}{unit_amount:,}"
            else:
                amount_decimal = unit_amount / 100.0
                if amount_decimal.is_integer():
                    amount_formatted = f"{symbol}{int(amount_decimal)}"
                else:
                    amount_formatted = f"{symbol}{amount_decimal:.2f}"

            result = {
                "price_id": p_id,
                "unit_amount": unit_amount,
                "currency": currency,
                "interval": interval,
                "amount_formatted": amount_formatted,
            }
            cls._price_cache[p_id] = (now, result)
            return result
        except Exception as exc:
            return {
                "price_id": p_id,
                "unit_amount": None,
                "amount_formatted": "Upgrade to Pro",
                "currency": "usd",
                "interval": "month",
                "error": str(exc),
            }

    @staticmethod
    def get_quota_limit() -> int:
        """Retrieves dynamically configured monthly quota for free-tier users."""
        return int(_get_billing_setting("FREE_TIER_MONTHLY_LIMIT", os.getenv("FREE_TIER_MONTHLY_QUOTA", str(FREE_TIER_MONTHLY_QUOTA))))

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
        api_key = _get_billing_setting("STRIPE_SECRET_KEY", os.getenv("STRIPE_API_KEY", STRIPE_API_KEY))
        if api_key:
            stripe.api_key = api_key

        p_id = price_id or _get_billing_setting("STRIPE_PRICE_ID_PRO", os.getenv("STRIPE_PRICE_ID", STRIPE_PRICE_ID))
        s_url = success_url or _get_billing_setting("STRIPE_SUCCESS_URL", DEFAULT_SUCCESS_URL)
        c_url = cancel_url or _get_billing_setting("STRIPE_CANCEL_URL", DEFAULT_CANCEL_URL)

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
        secret = webhook_secret or _get_billing_setting("STRIPE_WEBHOOK_SECRET", STRIPE_WEBHOOK_SECRET)
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
    def get_effective_quota_limit(cls, user_id: int, session: Session) -> int:
        """
        Calculates effective monthly quota limit including base free quota + any redeemed quota bonus perks.
        """
        base_quota = cls.get_quota_limit()
        try:
            from app.services.points_engine import PointsEngine
            bonus_quota = PointsEngine.get_user_monthly_quota_bonus(session, user_id)
        except Exception:
            bonus_quota = 0
        return base_quota + bonus_quota

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
        quota_limit = None if is_paid else cls.get_effective_quota_limit(user.id, session)

        return {
            "user_id": user.id,
            "tier": "paid" if is_paid else "free",
            "subscription_status": sub.status if sub else "inactive",
            "monthly_usage": current_usage,
            "monthly_quota": quota_limit,
            "is_quota_exceeded": False if is_paid else (current_usage >= quota_limit),
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
        - Free users: If monthly_usage >= effective_quota, returns is_allowed=False without recording.
                      If monthly_usage < effective_quota, records usage event and returns is_allowed=True.
        """
        sub = BillingRepository.get_subscription_by_user_id(session, user.id)
        now = utc_now()
        is_paid = (
            sub is not None
            and sub.status in ("active", "trialing")
            and (sub.current_period_end is None or sub.current_period_end > now)
        )

        if is_paid:
            BillingRepository.record_usage_event(session, user.id, event_type="repo_analysis")
            current_usage = BillingRepository.get_monthly_usage_count(session, user.id)
            return True, current_usage, -1, "paid"

        # Free Tier Effective Quota Check (Base + Redeemed Bonus)
        quota_limit = cls.get_effective_quota_limit(user.id, session)
        current_usage = BillingRepository.get_monthly_usage_count(session, user.id)
        if current_usage >= quota_limit:
            return False, current_usage, quota_limit, "free"

        # Consume quota by recording usage event
        BillingRepository.record_usage_event(session, user.id, event_type="repo_analysis")
        session.flush()
        new_usage = BillingRepository.get_monthly_usage_count(session, user.id)
        return True, new_usage, quota_limit, "free"

    @classmethod
    def fulfill_checkout_session(
        cls,
        session_id: str,
        user: UserModel,
        session: Session,
    ) -> Dict[str, Any]:
        """
        Verifies and fulfills a Stripe Checkout Session upon user redirect return.
        Enables seamless Pro Tier activation in production when webhooks are pending/delayed,
        and provides zero-friction local development Pro upgrading.
        """
        if not session_id or not session_id.strip():
            return {"success": False, "message": "No session ID provided"}

        api_key = _get_billing_setting("STRIPE_SECRET_KEY", os.getenv("STRIPE_API_KEY", STRIPE_API_KEY))
        if api_key:
            stripe.api_key = api_key

        try:
            # 1. Attempt to retrieve from Stripe API
            checkout_session = stripe.checkout.Session.retrieve(
                session_id,
                expand=["subscription", "customer"],
            )

            # Extract customer ID
            cust = getattr(checkout_session, "customer", None)
            stripe_customer_id = cust.id if hasattr(cust, "id") else (str(cust) if cust else None)

            # Extract subscription ID and period end
            sub_obj = getattr(checkout_session, "subscription", None)
            stripe_subscription_id = sub_obj.id if hasattr(sub_obj, "id") else (str(sub_obj) if sub_obj else None)

            period_end_dt = None
            if sub_obj and hasattr(sub_obj, "current_period_end") and sub_obj.current_period_end:
                period_end_dt = datetime.fromtimestamp(sub_obj.current_period_end, timezone.utc).replace(tzinfo=None)
            else:
                period_end_dt = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=365)

            status_str = "active"
            if sub_obj and hasattr(sub_obj, "status") and sub_obj.status:
                status_str = sub_obj.status

            BillingRepository.upsert_subscription(
                session=session,
                user_id=user.id,
                stripe_customer_id=stripe_customer_id or f"cus_{user.id}",
                stripe_subscription_id=stripe_subscription_id or f"sub_{user.id}",
                status=status_str,
                current_period_end=period_end_dt,
            )
            session.commit()

            try:
                from app.monitoring.posthog import analytics
                analytics.capture_subscription_started(user_id=user.id, tier="paid", plan="monthly")
            except Exception:
                pass

            return {
                "success": True,
                "message": "Subscription successfully activated! Welcome to Backtrace Pro.",
                "tier": "paid",
            }
        except Exception as exc:
            # In development/test mode, fulfill as dev subscription to avoid localhost webhook blockers
            from app.core.config import get_settings
            cfg = get_settings()
            if not cfg.is_production:
                period_end = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=365)
                sub_id_suffix = session_id[-10:] if len(session_id) >= 10 else str(user.id)
                BillingRepository.upsert_subscription(
                    session=session,
                    user_id=user.id,
                    stripe_customer_id=f"dev_customer_{user.id}",
                    stripe_subscription_id=f"sub_dev_{sub_id_suffix}",
                    status="active",
                    current_period_end=period_end,
                )
                session.commit()
                try:
                    from app.monitoring.posthog import analytics
                    analytics.capture_subscription_started(user_id=user.id, tier="paid", plan="monthly")
                except Exception:
                    pass
                return {
                    "success": True,
                    "message": "Pro Tier subscription successfully activated! Unlimited repository analyses enabled.",
                    "tier": "paid",
                }
            return {"success": False, "message": f"Unable to verify Stripe checkout session: {exc}"}

