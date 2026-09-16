"""Stripe Webhooks API Router with Cryptographic Signature Verification and Deduplication."""

from typing import Any, Dict
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.services.billing_service import BillingService, BillingServiceError

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/stripe", summary="Handle Verified Stripe Webhooks")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Receives, cryptographically verifies, and idempotently processes Stripe webhook events.
    Single source of truth for subscription status (checkout.session.completed,
    customer.subscription.updated, customer.subscription.deleted).
    """
    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required 'Stripe-Signature' header",
        )

    try:
        payload_bytes = await request.body()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to read raw webhook request payload: {exc}",
        )

    try:
        event = BillingService.verify_and_construct_webhook_event(
            payload_bytes=payload_bytes,
            sig_header=stripe_signature,
        )
        result = BillingService.process_webhook_event(
            event=event,
            session=session,
        )
        return result
    except BillingServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Webhook processing error: {exc}",
        )
