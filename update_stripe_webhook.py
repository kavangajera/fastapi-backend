import os

with open("routes/stripe_webhook.py", "w") as f:
    f.write('''import json
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status, BackgroundTasks
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import AsyncSessionLocal
from core.config import settings
from services.stripe_service import (
    handle_checkout_completed,
    handle_invoice_failed,
    handle_invoice_paid,
    handle_subscription_deleted,
    handle_subscription_updated,
)

router = APIRouter(prefix="/webhooks/stripe", tags=["Webhooks"])

async def process_stripe_event(event_type: str, data: dict):
    """Run webhook handling in the background with its own DB session."""
    try:
        async with AsyncSessionLocal() as db:
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
            await db.commit()
    except Exception as exc:
        logger.exception("Error handling webhook event {t}: {err}", t=event_type, err=exc)


@router.post("")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
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

    raw_event = json.loads(payload.decode("utf-8"))
    event_type = raw_event["type"]
    data = raw_event["data"]["object"]

    # Instantly schedule the database work in the background and return 200 OK!
    background_tasks.add_task(process_stripe_event, event_type, data)

    return {"status": "success", "message": "Event received and queued for background processing"}
''')

print("Updated")
