"""
routes/stripe_webhook.py
────────────────────────
Webhook endpoint for Stripe events.
"""

from __future__ import annotations

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.config import settings
from services.stripe_service import (
    handle_checkout_completed,
    handle_invoice_failed,
    handle_invoice_paid,
    handle_subscription_deleted,
    handle_subscription_updated,
)

router = APIRouter(prefix="/webhooks/stripe", tags=["Webhooks"])


@router.post("")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_async_db)):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header",
        )

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as exc:
        logger.error("Invalid payload: {err}", err=exc)
        raise HTTPException(status_code=400, detail="Invalid payload") from exc
    except stripe.SignatureVerificationError as exc:
        logger.error("Invalid signature: {err}", err=exc)
        raise HTTPException(status_code=400, detail="Invalid signature") from exc
    except Exception as exc:
        logger.error("Webhook processing error: {err}", err=exc)
        raise HTTPException(status_code=400, detail="Webhook processing error") from exc

    import json
    raw_event = json.loads(payload.decode("utf-8"))
    event_type = raw_event["type"]
    data = raw_event["data"]["object"]

    try:
        if event_type == "checkout.session.completed":
            await handle_checkout_completed(db, data)
        elif event_type == "invoice.paid":
            await handle_invoice_paid(db, data)
        elif event_type == "invoice.payment_failed":
            await handle_invoice_failed(db, data)
        elif event_type == "customer.subscription.deleted":
            await handle_subscription_deleted(db, data)
        elif event_type == "customer.subscription.updated":
            await handle_subscription_updated(db, data)
        else:
            logger.debug("Unhandled event type: {t}", t=event_type)
    except Exception as exc:
        logger.exception("Error handling webhook event {t}: {err}", t=event_type, err=exc)
        # We return 200 to Stripe so it doesn't keep retrying if it's a non-transient error on our end,
        # or we could return 500 if we want them to retry. Returning 200 for now.
        return {"status": "error", "message": str(exc)}

    return {"status": "success"}
