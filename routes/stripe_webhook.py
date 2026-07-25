"""
routes/stripe_webhook.py
────────────────────────
Webhook endpoint for Stripe events.

Instrumented with timed checkpoints ([CP-n]) so webhook delivery latency and
failures can be traced from the logs. Stripe marks a delivery as timed-out if
we don't respond within ~20s, so each checkpoint records the elapsed ms since
the request arrived — look for the gap between two checkpoints to find the slow
step (usually a blocking call back to Stripe's API inside a handler).
"""

from __future__ import annotations

import json
from time import perf_counter

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
        event = stripe.Webhook.construct_event(
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

    logger.info("[CP-4] signature verified OK +{t}ms", t=ms())

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

    handlers = {
        "checkout.session.completed": handle_checkout_completed,
        "invoice.paid": handle_invoice_paid,
        "invoice.payment_failed": handle_invoice_failed,
        "customer.subscription.deleted": handle_subscription_deleted,
        "customer.subscription.updated": handle_subscription_updated,
    }
    handler = handlers.get(event_type)

    if handler is None:
        logger.info("[CP-6] no handler for event type={et} — skipping +{t}ms", et=event_type, t=ms())
        logger.info("[CP-9] responding 200 (unhandled) total={t}ms", t=ms())
        return {"status": "ignored", "event_type": event_type}

    logger.info("[CP-6] dispatching handler for {et}… +{t}ms", et=event_type, t=ms())
    try:
        await handler(db, data)
    except Exception as exc:
        logger.exception(
            "[CP-7] ERROR in handler for event {et} (id={eid}): {err} +{t}ms",
            et=event_type,
            eid=event_id,
            err=exc,
            t=ms(),
        )
        # We return 200 to Stripe so it doesn't keep retrying if it's a non-transient error on our end,
        # or we could return 500 if we want them to retry. Returning 200 for now.
        logger.info("[CP-9] responding 200 (handler error) total={t}ms", t=ms())
        return {"status": "error", "message": str(exc)}

    logger.info("[CP-8] handler for {et} completed OK +{t}ms", et=event_type, t=ms())
    logger.info("[CP-9] responding 200 (success) total={t}ms", t=ms())
    return {"status": "success"}
