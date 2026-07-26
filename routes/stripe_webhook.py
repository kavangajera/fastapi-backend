import json

import json
from time import perf_counter

import stripe
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from loguru import logger

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
    t0 = perf_counter()

    def ms() -> float:
        """Elapsed milliseconds since the request arrived."""
        return round((perf_counter() - t0) * 1000, 1)

    logger.info(
        "[CP-1] stripe webhook request received: client={c} content_length={cl}",
        c=getattr(request.client, "host", "unknown"),
        cl=request.headers.get("content-length"),
    )

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    logger.info(
        "[CP-2] body read: payload_bytes={n} has_signature={s} +{t}ms",
        n=len(payload),
        s=bool(sig_header),
        t=ms(),
    )

    if not sig_header:
        logger.warning("[CP-2a] missing stripe-signature header — rejecting 400 +{t}ms", t=ms())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header",
        )

    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error("[CP-3a] STRIPE_WEBHOOK_SECRET is EMPTY — signature verification will fail +{t}ms", t=ms())

    logger.info("[CP-3] verifying signature… +{t}ms", t=ms())
    try:
        stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as exc:
        logger.error("[CP-3b] invalid payload: {err} +{t}ms", err=exc, t=ms())
        raise HTTPException(status_code=400, detail="Invalid payload") from exc
    except stripe.SignatureVerificationError as exc:
        logger.error("[CP-3b] invalid signature: {err} +{t}ms", err=exc, t=ms())
        raise HTTPException(status_code=400, detail="Invalid signature") from exc
    except Exception as exc:
        logger.error("[CP-3b] webhook construct error: {err} +{t}ms", err=exc, t=ms())
        raise HTTPException(status_code=400, detail="Webhook processing error") from exc

    raw_event = json.loads(payload.decode("utf-8"))
    event_type = raw_event["type"]
    event_id = raw_event.get("id")
    data = raw_event["data"]["object"]
    logger.info(
        "[CP-5] event parsed: type={et} id={eid} obj_id={oid} +{t}ms",
        et=event_type,
        eid=event_id,
        oid=data.get("id") if isinstance(data, dict) else None,
        t=ms(),
    )

    # Instantly schedule the database work in the background and return 200 OK!
    background_tasks.add_task(process_stripe_event, event_type, data)

    return {"status": "success", "message": "Event received and queued for background processing"}
