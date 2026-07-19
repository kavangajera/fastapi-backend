"""
schemas/payment_schemas.py
──────────────────────────
Request/response models for Stripe payment & checkout flows.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CheckoutSessionResponse(BaseModel):
    """Returned after creating a Stripe Checkout Session."""
    checkout_url: str = Field(..., description="Stripe Checkout URL — redirect the user here")
    session_id: str = Field(..., description="Stripe Checkout Session ID")


class PaymentOut(BaseModel):
    """Individual payment record."""
    model_config = ConfigDict(from_attributes=True)

    payment_id: int
    subscription_id: int
    medical_store_id: int
    stripe_payment_intent_id: str | None = None
    stripe_invoice_id: str | None = None
    amount_cents: int
    currency: str
    status: str
    paid_at: datetime | None = None
    failure_reason: str | None = None


class PaymentListResponse(BaseModel):
    """Paginated payment history."""
    payments: list[PaymentOut]
    total: int
