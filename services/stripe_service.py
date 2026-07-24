"""
services/stripe_service.py
──────────────────────────
Stripe integration for subscription billing.

Handles:
- Customer management (pharmacy → Stripe Customer)
- Plan sync (Plan → Stripe Product + Price)
- Checkout Sessions (subscribe flow)
- Subscription modifications (upgrade/downgrade)
- Cancellation
- Webhook event processing
"""

from __future__ import annotations

from datetime import datetime, timezone

import stripe
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.payment import SubscriptionPayment
from models.pharmacy import Pharmacy
from models.plan import Plan
from models.subscription import Subscription, SubscriptionEvent

stripe.api_key = settings.STRIPE_SECRET_KEY


async def get_or_create_customer(
    db: AsyncSession, pharmacy: Pharmacy, owner_email: str
) -> str:
    """Return existing or newly created Stripe Customer ID."""
    if pharmacy.stripe_customer_id:
        return pharmacy.stripe_customer_id

    customer = stripe.Customer.create(
        name=pharmacy.name,
        email=owner_email,
        address={"country": "US"},
        metadata={
            "medical_store_id": str(pharmacy.medical_store_id),
            "pharmacy_name": pharmacy.name,
        },
    )
    pharmacy.stripe_customer_id = customer.id
    await db.commit()
    logger.info(
        "Stripe customer created: cust_id={cid} ms_id={ms}",
        cid=customer.id,
        ms=pharmacy.medical_store_id,
    )
    return customer.id


async def ensure_plan_synced(db: AsyncSession, plan: Plan) -> tuple[str, str]:
    """Ensure Plan has Stripe Product + Price. Returns (product_id, price_id)."""
    if plan.stripe_product_id and plan.stripe_price_id:
        return plan.stripe_product_id, plan.stripe_price_id

    if not plan.stripe_product_id:
        product = stripe.Product.create(
            name=plan.name,
            description=plan.description or f"{plan.code} plan",
            metadata={"plan_id": str(plan.plan_id), "plan_code": plan.code},
        )
        plan.stripe_product_id = product.id
        logger.info("Stripe product created: prod_id={pid} plan={c}", pid=product.id, c=plan.code)

    if not plan.stripe_price_id:
        price = stripe.Price.create(
            product=plan.stripe_product_id,
            unit_amount=plan.monthly_price_cents,
            currency="usd",
            recurring={"interval": "month"},
            metadata={"plan_id": str(plan.plan_id), "plan_code": plan.code},
        )
        plan.stripe_price_id = price.id
        logger.info("Stripe price created: price_id={pid} plan={c}", pid=price.id, c=plan.code)

    await db.commit()
    return plan.stripe_product_id, plan.stripe_price_id


async def create_checkout_session(
    db: AsyncSession,
    pharmacy: Pharmacy,
    plan: Plan,
    owner_email: str,
    medical_store_id: int,
) -> stripe.checkout.Session:
    """Create a Stripe Checkout Session for a new subscription."""
    customer_id = await get_or_create_customer(db, pharmacy, owner_email)
    _, price_id = await ensure_plan_synced(db, plan)

    base_url = settings.FRONTEND_URL if settings.FRONTEND_URL.startswith("http") else f"http://{settings.FRONTEND_URL}"
    
    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=(
            f"{base_url}/subscription/success"
            f"?session_id={{CHECKOUT_SESSION_ID}}&medical_store_id={medical_store_id}"
        ),
        cancel_url=(
            f"{base_url}/subscription/cancel"
            f"?medical_store_id={medical_store_id}"
        ),
        metadata={
            "medical_store_id": str(medical_store_id),
            "plan_id": str(plan.plan_id),
            "plan_code": plan.code,
        },
    )
    logger.info(
        "Checkout session created: session={sid} ms_id={ms} plan={p}",
        sid=session.id,
        ms=medical_store_id,
        p=plan.code,
    )
    return session


async def modify_subscription(
    db: AsyncSession,
    subscription: Subscription,
    new_plan: Plan,
) -> stripe.Subscription:
    """Upgrade/downgrade an active Stripe subscription with proration."""
    if not subscription.stripe_subscription_id:
        raise ValueError("Subscription has no Stripe subscription ID")

    _, new_price_id = await ensure_plan_synced(db, new_plan)

    stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
    
    # In a real app we should handle pagination if a sub has multiple items,
    # but here we assume one subscription item (the plan).
    items = getattr(stripe_sub.items, "data", []) if hasattr(stripe_sub, "items") else []
    if not items:
        raise ValueError("Stripe subscription has no items")
        
    item_id = getattr(items[0], "id", None)
    if not item_id and isinstance(items[0], dict):
        item_id = items[0].get("id")

    updated = stripe.Subscription.modify(
        subscription.stripe_subscription_id,
        items=[{
            "id": item_id,
            "price": new_price_id,
        }],
        proration_behavior="always_invoice",
        metadata={
            "plan_id": str(new_plan.plan_id),
            "plan_code": new_plan.code,
        },
    )
    logger.info(
        "Stripe subscription modified: sub={sid} new_plan={p}",
        sid=subscription.stripe_subscription_id,
        p=new_plan.code,
    )
    return updated



def _get_period_end(stripe_sub) -> int:
    if hasattr(stripe_sub, "current_period_end"):
        return stripe_sub.current_period_end
    if isinstance(stripe_sub, dict) and "current_period_end" in stripe_sub:
        return stripe_sub["current_period_end"]
        
    items = getattr(stripe_sub, "items", None) or (stripe_sub.get("items") if isinstance(stripe_sub, dict) else {})
    data = getattr(items, "data", None) or (items.get("data") if isinstance(items, dict) else [])
    
    if data:
        item = data[0]
        if hasattr(item, "current_period_end"):
            return item.current_period_end
        if isinstance(item, dict) and "current_period_end" in item:
            return item["current_period_end"]
            
    # Fallback to created + 30 days
    return (getattr(stripe_sub, "created", None) or (stripe_sub.get("created") if isinstance(stripe_sub, dict) else 0)) + 2592000


def cancel_stripe_subscription(
    stripe_subscription_id: str, immediately: bool = False
) -> stripe.Subscription:
    """Cancel a Stripe subscription (at period end or immediately)."""
    if immediately:
        result = stripe.Subscription.cancel(stripe_subscription_id)
        logger.info("Stripe subscription cancelled immediately: {sid}", sid=stripe_subscription_id)
    else:
        result = stripe.Subscription.modify(
            stripe_subscription_id,
            cancel_at_period_end=True,
        )
        logger.info("Stripe subscription set to cancel at period end: {sid}", sid=stripe_subscription_id)
    return result


# ── Webhook handlers ──────────────────────────────────────────────────────


async def handle_checkout_completed(
    db: AsyncSession, session: dict
) -> None:
    """Webhook: checkout.session.completed — activate the subscription."""
    metadata = session.get("metadata", {})
    if not metadata.get("medical_store_id") or not metadata.get("plan_id"):
        return
        
    medical_store_id = int(metadata["medical_store_id"])
    plan_id = int(metadata["plan_id"])
    stripe_sub_id = session.get("subscription")

    # Get or create subscription row
    result = await db.execute(
        select(Subscription).where(
            Subscription.medical_store_id == medical_store_id
        ).order_by(Subscription.subscription_id.desc()).limit(1)
    )
    sub = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    # Get period end from Stripe subscription
    stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)
    period_end = datetime.fromtimestamp(_get_period_end(stripe_sub), tz=timezone.utc)

    if sub:
        sub.plan_id = plan_id
        sub.status = "ACTIVE"
        sub.started_at = now
        sub.current_period_end = period_end
        sub.stripe_subscription_id = stripe_sub_id
        sub.stripe_checkout_session_id = session["id"]
        sub.cancelled_at = None
    else:
        sub = Subscription(
            medical_store_id=medical_store_id,
            plan_id=plan_id,
            status="ACTIVE",
            started_at=now,
            current_period_end=period_end,
            stripe_subscription_id=stripe_sub_id,
            stripe_checkout_session_id=session["id"],
        )
        db.add(sub)
        await db.flush()

    # Log subscription event
    event = SubscriptionEvent(
        subscription_id=sub.subscription_id,
        action="SUBSCRIBE",
        to_plan_id=plan_id,
        detail={"stripe_session_id": session["id"], "stripe_subscription_id": stripe_sub_id},
    )
    db.add(event)
    
    # Handle the race condition where invoice.paid arrives before checkout.session.completed
    invoice_id = session.get("invoice")
    if invoice_id:
        # Check if we already logged this payment
        from models.payment import SubscriptionPayment
        existing_payment = await db.execute(
            select(SubscriptionPayment).where(SubscriptionPayment.stripe_invoice_id == invoice_id)
        )
        if not existing_payment.scalar_one_or_none():
            invoice = stripe.Invoice.retrieve(invoice_id)
            if getattr(invoice, "status", None) == "paid":
                payment = SubscriptionPayment(
                    subscription_id=sub.subscription_id,
                    medical_store_id=sub.medical_store_id,
                    stripe_payment_intent_id=getattr(invoice, "payment_intent", None),
                    stripe_invoice_id=invoice_id,
                    amount_cents=getattr(invoice, "amount_paid", 0),
                    currency=getattr(invoice, "currency", "usd"),
                    status="SUCCESS",
                    paid_at=datetime.now(timezone.utc),
                )
                db.add(payment)

    await db.commit()
    logger.info(
        "Subscription activated via checkout: ms_id={ms} plan_id={p} stripe_sub={s}",
        ms=medical_store_id,
        p=plan_id,
        s=stripe_sub_id,
    )


async def handle_invoice_paid(
    db: AsyncSession, invoice: dict
) -> None:
    """Webhook: invoice.paid — log payment and extend subscription period."""
    stripe_sub_id = invoice.get("subscription")
    if not stripe_sub_id:
        return  # Not a subscription invoice

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        logger.warning("invoice.paid: no subscription for stripe_sub={s}", s=stripe_sub_id)
        return

    # Update subscription period from Stripe
    stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)
    sub.current_period_end = datetime.fromtimestamp(
        _get_period_end(stripe_sub), tz=timezone.utc
    )
    sub.status = "ACTIVE"

    # Log payment
    payment = SubscriptionPayment(
        subscription_id=sub.subscription_id,
        medical_store_id=sub.medical_store_id,
        stripe_payment_intent_id=invoice.get("payment_intent"),
        stripe_invoice_id=invoice.get("id"),
        amount_cents=invoice.get("amount_paid", 0),
        currency=invoice.get("currency", "usd"),
        status="SUCCESS",
        paid_at=datetime.now(timezone.utc),
    )
    db.add(payment)

    # Log renewal event
    event = SubscriptionEvent(
        subscription_id=sub.subscription_id,
        action="RENEW",
        to_plan_id=sub.plan_id,
        detail={"stripe_invoice_id": invoice.get("id"), "amount_cents": invoice.get("amount_paid")},
    )
    db.add(event)

    await db.commit()
    logger.info(
        "Payment recorded + subscription renewed: sub_id={sid} amount={a}",
        sid=sub.subscription_id,
        a=invoice.get("amount_paid"),
    )


async def handle_invoice_failed(
    db: AsyncSession, invoice: dict
) -> None:
    """Webhook: invoice.payment_failed — log failed payment."""
    stripe_sub_id = invoice.get("subscription")
    if not stripe_sub_id:
        return

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return

    # Attempt to extract failure reason safely
    error_msg = "Payment failed"
    lfe = invoice.get("last_finalization_error")
    if isinstance(lfe, dict):
        error_msg = lfe.get("message", "Payment failed")

    payment = SubscriptionPayment(
        subscription_id=sub.subscription_id,
        medical_store_id=sub.medical_store_id,
        stripe_payment_intent_id=invoice.get("payment_intent"),
        stripe_invoice_id=invoice.get("id"),
        amount_cents=invoice.get("amount_due", 0),
        currency=invoice.get("currency", "usd"),
        status="FAILED",
        failure_reason=error_msg,
    )
    db.add(payment)
    await db.commit()
    logger.warning(
        "Payment failed: sub_id={sid} invoice={inv}",
        sid=sub.subscription_id,
        inv=invoice.get("id"),
    )


async def handle_subscription_deleted(
    db: AsyncSession, stripe_sub: dict
) -> None:
    """Webhook: customer.subscription.deleted — mark subscription cancelled."""
    stripe_sub_id = stripe_sub.get("id")
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return

    sub.status = "CANCELLED"
    sub.cancelled_at = datetime.now(timezone.utc)

    event = SubscriptionEvent(
        subscription_id=sub.subscription_id,
        action="REVOKE",
        detail={"source": "stripe_webhook", "stripe_subscription_id": stripe_sub_id},
    )
    db.add(event)
    await db.commit()
    logger.info("Subscription cancelled via webhook: sub_id={sid}", sid=sub.subscription_id)


async def handle_subscription_updated(
    db: AsyncSession, stripe_sub: dict
) -> None:
    """Webhook: customer.subscription.updated — sync plan changes from Stripe."""
    stripe_sub_id = stripe_sub.get("id")
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id).order_by(Subscription.subscription_id.desc()).limit(1)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return

    # Update period end
    sub.current_period_end = datetime.fromtimestamp(_get_period_end(stripe_sub), tz=timezone.utc)

    # Check if plan changed (via price)
    items = stripe_sub.get("items", {}).get("data", [])
    if items:
        stripe_price_id = items[0].get("price", {}).get("id")
        if stripe_price_id:
            plan_result = await db.execute(
                select(Plan).where(Plan.stripe_price_id == stripe_price_id)
            )
            new_plan = plan_result.scalar_one_or_none()
            if new_plan and new_plan.plan_id != sub.plan_id:
                # get old plan
                old_plan_result = await db.execute(select(Plan).where(Plan.plan_id == sub.plan_id))
                old_plan = old_plan_result.scalar_one_or_none()
                
                old_plan_id = sub.plan_id
                sub.plan_id = new_plan.plan_id
                
                action = "UPGRADE"
                if old_plan and new_plan.tier < old_plan.tier:
                    action = "DOWNGRADE"
                    
                event = SubscriptionEvent(
                    subscription_id=sub.subscription_id,
                    action=action,
                    from_plan_id=old_plan_id,
                    to_plan_id=new_plan.plan_id,
                    detail={"source": "stripe_webhook"},
                )
                db.add(event)

    # Sync status
    stripe_status = stripe_sub.get("status")
    if stripe_status == "active":
        sub.status = "ACTIVE"
        sub.cancelled_at = None
    elif stripe_status in ("canceled", "unpaid"):
        sub.status = "CANCELLED"
        if not sub.cancelled_at:
            sub.cancelled_at = datetime.now(timezone.utc)
    elif stripe_status == "past_due":
        # Keep active but period_end will handle expiry
        pass

    await db.commit()
    logger.info(
        "Subscription synced from Stripe: sub_id={sid} status={st}",
        sid=sub.subscription_id,
        st=stripe_sub.get("status"),
    )
