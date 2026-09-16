"""Billing and Subscription API Router for Stripe Hosted Checkout and Customer Portal."""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.models.db import UserModel
from app.services.billing_service import BillingService, BillingServiceError

router = APIRouter(prefix="/billing", tags=["Billing"])


class CheckoutSessionRequest(BaseModel):
    success_url: Optional[str] = Field(None, description="Optional custom post-payment return URL")
    cancel_url: Optional[str] = Field(None, description="Optional cancellation return URL")


class CustomerPortalRequest(BaseModel):
    return_url: Optional[str] = Field(None, description="Optional return URL from customer portal")


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class CustomerPortalResponse(BaseModel):
    portal_url: str


class BillingStatusResponse(BaseModel):
    user_id: int
    tier: str
    subscription_status: str
    monthly_usage: int
    monthly_quota: Optional[int]
    is_quota_exceeded: bool
    current_period_end: Optional[str]


@router.post("/checkout", response_model=CheckoutSessionResponse, summary="Create Stripe Checkout Session")
def create_checkout(
    payload: Optional[CheckoutSessionRequest] = None,
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Creates a hosted Stripe Checkout Session for upgrading the authenticated user to the Paid tier.
    Zero-PCI compliance: Redirects to Stripe hosted checkout page.
    """
    s_url = payload.success_url if payload else None
    c_url = payload.cancel_url if payload else None

    try:
        url = BillingService.create_checkout_session(
            user=current_user,
            session=session,
            success_url=s_url,
            cancel_url=c_url,
        )
        return CheckoutSessionResponse(checkout_url=url)
    except BillingServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create Stripe Checkout session: {exc}",
        )


@router.post("/portal", response_model=CustomerPortalResponse, summary="Create Stripe Customer Portal Session")
def create_customer_portal(
    payload: Optional[CustomerPortalRequest] = None,
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Creates a hosted Stripe Customer Portal Session for managing subscription and payment methods.
    Derived strictly from the authenticated user's verified customer record.
    """
    r_url = payload.return_url if payload else None

    try:
        url = BillingService.create_customer_portal_session(
            user=current_user,
            session=session,
            return_url=r_url,
        )
        return CustomerPortalResponse(portal_url=url)
    except BillingServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create Customer Portal session: {exc}",
        )


@router.get("/status", response_model=BillingStatusResponse, summary="Get Current Subscription and Quota Status")
def get_billing_status(
    current_user: UserModel = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Returns current user's subscription tier ('free' vs 'paid'), monthly quota usage, and expiration status.
    """
    status_data = BillingService.get_user_billing_status(user=current_user, session=session)
    return BillingStatusResponse(**status_data)
