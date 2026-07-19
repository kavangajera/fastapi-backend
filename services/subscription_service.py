"""
services/subscription_service.py
────────────────────────────────
Business logic for a pharmacy's subscription lifecycle.

Billing integration (Stripe/webhooks, proration) enabled.
Subscribe and upgrade now delegate to Stripe checkout sessions.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import SubscriptionStatus
from models.pharmacy import Pharmacy
from models.plan import Plan
from models.subscription import Subscription, SubscriptionEvent
from models.user import User
from services.plan_service import get_plan, get_plan_by_code
from services.stripe_service import (
    cancel_stripe_subscription,
    create_checkout_session,
    modify_subscription,
)

SUBSCRIPTION_PERIOD_DAYS = 30


def _raise(status_code: int, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
    )


def _period_end(start: datetime | None = None) -> datetime:
    start = start or datetime.utcnow()
    return start + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)


def _log_event(
    db: AsyncSession,
    subscription: Subscription,
    action: str,
    *,
    from_plan_id: int | None = None,
    to_plan_id: int | None = None,
    actor_user_id: int | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        SubscriptionEvent(
            subscription_id=subscription.subscription_id,
            action=action,
            from_plan_id=from_plan_id,
            to_plan_id=to_plan_id,
            actor_user_id=actor_user_id,
            detail=detail,
        )
    )


async def _get_live_subscription(db: AsyncSession, medical_store_id: int) -> Subscription | None:
    result = await db.execute(
        select(Subscription)
        .where(Subscription.medical_store_id == medical_store_id)
        .order_by(Subscription.subscription_id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_for_store(db: AsyncSession, medical_store_id: int) -> Subscription | None:
    return await _get_live_subscription(db, medical_store_id)


async def list_subscriptions(
    db: AsyncSession,
    *,
    status_filter: str | None = None,
    plan_id: int | None = None,
    medical_store_id: int | None = None,
) -> list[Subscription]:
    stmt = select(Subscription).order_by(Subscription.subscription_id.desc())
    if status_filter:
        stmt = stmt.where(Subscription.status == status_filter)
    if plan_id is not None:
        stmt = stmt.where(Subscription.plan_id == plan_id)
    if medical_store_id is not None:
        stmt = stmt.where(Subscription.medical_store_id == medical_store_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _resolve_plan_by_code(db: AsyncSession, plan_code: str) -> Plan:
    plan = await get_plan_by_code(db, plan_code)
    if plan is None:
        _raise(404, f"Plan '{plan_code}' not found")
    if not plan.is_active:
        _raise(409, f"Plan '{plan_code}' is not available")
    return plan


async def subscribe(
    db: AsyncSession,
    *,
    medical_store_id: int,
    plan_code: str,
    actor_user_id: int,
) -> str:
    """Start or (re)activate the store's subscription on ``plan_code`` via Stripe."""
    plan = await _resolve_plan_by_code(db, plan_code)
    sub = await _get_live_subscription(db, medical_store_id)
    
    if sub and sub.status == SubscriptionStatus.ACTIVE.value:
        _raise(409, "Pharmacy already has an active subscription. Use upgrade endpoint.")
        
    pharmacy = await db.get(Pharmacy, medical_store_id)
    if not pharmacy:
        _raise(404, "Pharmacy not found")
        
    user = await db.get(User, actor_user_id)
    if not user:
        _raise(404, "User not found")
        
    try:
        session = await create_checkout_session(
            db,
            pharmacy,
            plan,
            user.email or "owner@example.com",
            medical_store_id
        )
        return session.url
    except Exception as exc:
        logger.error("Failed to create Stripe checkout session: {err}", err=str(exc))
        _raise(500, f"Payment gateway error: {str(exc)}")


async def upgrade(
    db: AsyncSession,
    *,
    medical_store_id: int,
    plan_code: str,
    actor_user_id: int | None,
) -> Subscription:
    """Change the store's plan via Stripe (with proration)."""
    sub = await _get_live_subscription(db, medical_store_id)
    if sub is None or sub.status != SubscriptionStatus.ACTIVE.value:
        _raise(404, "No active subscription to change for this pharmacy. Subscribe first.")

    new_plan = await _resolve_plan_by_code(db, plan_code)
    old_plan = await get_plan(db, sub.plan_id)
    if old_plan is not None and old_plan.plan_id == new_plan.plan_id:
        _raise(409, "Pharmacy is already on this plan")
        
    if not sub.stripe_subscription_id:
        _raise(400, "Cannot upgrade legacy subscriptions via Stripe. Please cancel and re-subscribe.")

    try:
        await modify_subscription(db, sub, new_plan)
        await db.commit()
        # Webhook will handle DB updates for the new plan
    except Exception as exc:
        logger.error("Failed to modify Stripe subscription: {err}", err=str(exc))
        _raise(500, f"Payment gateway error: {str(exc)}")
        
    return sub


async def cancel(
    db: AsyncSession,
    *,
    medical_store_id: int,
    actor_user_id: int | None,
    immediately: bool = False
) -> Subscription:
    """Cancel subscription via Stripe."""
    sub = await _get_live_subscription(db, medical_store_id)
    if sub is None or sub.status != SubscriptionStatus.ACTIVE.value:
        _raise(404, "No active subscription to cancel")
        
    if not sub.stripe_subscription_id:
        # Legacy
        sub.status = SubscriptionStatus.CANCELLED.value
        sub.cancelled_at = datetime.utcnow()
        if immediately:
            sub.current_period_end = sub.cancelled_at
        await db.commit()
        return sub

    try:
        cancel_stripe_subscription(sub.stripe_subscription_id, immediately)
        # Webhook will handle DB updates for cancelled status
    except Exception as exc:
        logger.error("Failed to cancel Stripe subscription: {err}", err=str(exc))
        _raise(500, f"Payment gateway error: {str(exc)}")
        
    return sub


async def admin_assign(
    db: AsyncSession,
    *,
    medical_store_id: int,
    plan_code: str,
    current_period_end: datetime | None,
    status_value: str | None,
    actor_user_id: int | None,
    notes: str | None = None,
) -> Subscription:
    """Admin override: force a plan/expiry/status onto a store's subscription."""
    plan = await _resolve_plan_by_code(db, plan_code)
    now = datetime.utcnow()
    sub = await _get_live_subscription(db, medical_store_id)
    is_new = sub is None
    if is_new:
        sub = Subscription(medical_store_id=medical_store_id)
        db.add(sub)

    from_plan_id = None if is_new else sub.plan_id
    sub.plan_id = plan.plan_id
    sub.status = status_value or SubscriptionStatus.ACTIVE.value
    sub.started_at = now
    sub.current_period_end = current_period_end or _period_end(now)
    sub.cancelled_at = (
        now if sub.status == SubscriptionStatus.CANCELLED.value else None
    )
    if notes is not None:
        sub.notes = notes

    try:
        await db.flush()
        _log_event(
            db,
            sub,
            "ADMIN_MODIFY",
            from_plan_id=from_plan_id,
            to_plan_id=plan.plan_id,
            actor_user_id=actor_user_id,
            detail={"assigned": True, "status": sub.status},
        )
        await db.commit()
        await db.refresh(sub)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Admin assign failed for store {s}: {err}", s=medical_store_id, err=str(exc))
        _raise(500, "Failed to assign subscription")
    return sub


async def admin_modify(
    db: AsyncSession,
    *,
    subscription_id: int,
    plan_code: str | None,
    status_value: str | None,
    current_period_end: datetime | None,
    notes: str | None,
    actor_user_id: int | None,
) -> Subscription:
    """Admin edit of an existing subscription by id (plan / status / expiry)."""
    sub = await db.get(Subscription, subscription_id)
    if sub is None:
        _raise(404, "Subscription not found")

    from_plan_id = sub.plan_id
    to_plan_id = sub.plan_id
    if plan_code is not None:
        plan = await _resolve_plan_by_code(db, plan_code)
        sub.plan_id = plan.plan_id
        to_plan_id = plan.plan_id
    if current_period_end is not None:
        sub.current_period_end = current_period_end
    if status_value is not None:
        sub.status = status_value
        sub.cancelled_at = (
            datetime.utcnow() if status_value == SubscriptionStatus.CANCELLED.value else None
        )
    if notes is not None:
        sub.notes = notes

    try:
        _log_event(
            db,
            sub,
            "ADMIN_MODIFY",
            from_plan_id=from_plan_id,
            to_plan_id=to_plan_id,
            actor_user_id=actor_user_id,
            detail={"status": sub.status},
        )
        await db.commit()
        await db.refresh(sub)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Admin modify failed for sub {i}: {err}", i=subscription_id, err=str(exc))
        _raise(500, "Failed to modify subscription")
    return sub


async def revoke(
    db: AsyncSession,
    *,
    subscription_id: int,
    actor_user_id: int | None,
) -> Subscription:
    """Admin revoke: cancel immediately and expire access now."""
    sub = await db.get(Subscription, subscription_id)
    if sub is None:
        _raise(404, "Subscription not found")

    now = datetime.utcnow()
    from_plan_id = sub.plan_id
    sub.status = SubscriptionStatus.CANCELLED.value
    sub.cancelled_at = now
    sub.current_period_end = now  # cut access off immediately (no grace)

    try:
        if sub.stripe_subscription_id:
            cancel_stripe_subscription(sub.stripe_subscription_id, immediately=True)
            
        _log_event(
            db,
            sub,
            "REVOKE",
            from_plan_id=from_plan_id,
            to_plan_id=from_plan_id,
            actor_user_id=actor_user_id,
        )
        await db.commit()
        await db.refresh(sub)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Revoke failed for sub {i}: {err}", i=subscription_id, err=str(exc))
        _raise(500, "Failed to revoke subscription")
    except Exception as exc:
        logger.error("Stripe revoke failed for sub {i}: {err}", i=subscription_id, err=str(exc))
        _raise(500, f"Stripe error: {str(exc)}")
    return sub
