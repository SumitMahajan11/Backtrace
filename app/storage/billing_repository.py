"""Data Access Layer (Repository Pattern) for Subscriptions, Usage Events, and Webhook Deduplication."""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.db import (
    ProcessedWebhookEventModel,
    SubscriptionModel,
    UsageEventModel,
    utc_now,
)


class BillingRepository:
    """Repository managing database persistence for Stripe subscriptions and usage audit logs."""

    @staticmethod
    def get_subscription_by_user_id(session: Session, user_id: int) -> Optional[SubscriptionModel]:
        """Retrieves subscription record by internal user ID."""
        stmt = select(SubscriptionModel).where(SubscriptionModel.user_id == user_id)
        return session.scalar(stmt)

    @staticmethod
    def get_subscription_by_stripe_customer_id(
        session: Session, stripe_customer_id: str
    ) -> Optional[SubscriptionModel]:
        """Retrieves subscription record by Stripe customer ID."""
        stmt = select(SubscriptionModel).where(SubscriptionModel.stripe_customer_id == stripe_customer_id)
        return session.scalar(stmt)

    @staticmethod
    def get_subscription_by_stripe_subscription_id(
        session: Session, stripe_subscription_id: str
    ) -> Optional[SubscriptionModel]:
        """Retrieves subscription record by Stripe subscription ID."""
        stmt = select(SubscriptionModel).where(SubscriptionModel.stripe_subscription_id == stripe_subscription_id)
        return session.scalar(stmt)

    @staticmethod
    def upsert_subscription(
        session: Session,
        user_id: int,
        stripe_customer_id: str,
        stripe_subscription_id: Optional[str] = None,
        status: str = "active",
        current_period_end: Optional[datetime] = None,
    ) -> SubscriptionModel:
        """
        Upserts subscription record: creates new row or updates existing user subscription.
        """
        sub = BillingRepository.get_subscription_by_user_id(session, user_id)
        now = utc_now()
        if sub:
            sub.stripe_customer_id = stripe_customer_id
            if stripe_subscription_id is not None:
                sub.stripe_subscription_id = stripe_subscription_id
            sub.status = status
            if current_period_end is not None:
                sub.current_period_end = current_period_end
            sub.updated_at = now
            session.flush()
            return sub

        sub = SubscriptionModel(
            user_id=user_id,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            status=status,
            current_period_end=current_period_end,
            created_at=now,
            updated_at=now,
        )
        session.add(sub)
        session.flush()
        return sub

    @staticmethod
    def update_subscription_status(
        session: Session,
        stripe_subscription_id: str,
        status: str,
        current_period_end: Optional[datetime] = None,
    ) -> Optional[SubscriptionModel]:
        """Updates subscription status and period end by Stripe subscription ID."""
        sub = BillingRepository.get_subscription_by_stripe_subscription_id(session, stripe_subscription_id)
        if sub:
            sub.status = status
            if current_period_end is not None:
                sub.current_period_end = current_period_end
            sub.updated_at = utc_now()
            session.flush()
        return sub

    @staticmethod
    def record_usage_event(
        session: Session,
        user_id: int,
        event_type: str = "repo_analysis",
    ) -> UsageEventModel:
        """Records an immutable analysis event in the usage audit log."""
        event = UsageEventModel(
            user_id=user_id,
            event_type=event_type,
            created_at=utc_now(),
        )
        session.add(event)
        session.flush()
        return event

    @staticmethod
    def get_monthly_usage_count(
        session: Session,
        user_id: int,
        reference_date: Optional[datetime] = None,
    ) -> int:
        """
        Counts usage events for the current calendar month.
        Enables precise monthly quota resets without periodic cron jobs.
        """
        ref = reference_date or utc_now()
        month_start = datetime(ref.year, ref.month, 1)

        stmt = (
            select(func.count(UsageEventModel.id))
            .where(
                UsageEventModel.user_id == user_id,
                UsageEventModel.event_type == "repo_analysis",
                UsageEventModel.created_at >= month_start,
            )
        )
        count = session.scalar(stmt)
        return int(count or 0)

    @staticmethod
    def is_webhook_event_processed(session: Session, event_id: str) -> bool:
        """Checks if a Stripe webhook event ID has already been recorded and processed."""
        stmt = select(ProcessedWebhookEventModel).where(ProcessedWebhookEventModel.event_id == event_id)
        return session.scalar(stmt) is not None

    @staticmethod
    def record_processed_webhook_event(
        session: Session,
        event_id: str,
        event_type: str,
    ) -> ProcessedWebhookEventModel:
        """Records a Stripe webhook event ID for deduplication."""
        event_rec = ProcessedWebhookEventModel(
            event_id=event_id,
            event_type=event_type,
            processed_at=utc_now(),
        )
        session.add(event_rec)
        session.flush()
        return event_rec
