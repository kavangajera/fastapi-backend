"""
services/feature_gate.py
────────────────────────
The subscription entitlement guard used by every gated route.

Placement mirrors the existing authz convention: call it at the route level
right after ``ensure_pharmacy_access(db, user, medical_store_id)``, e.g.

    await ensure_pharmacy_access(db, user, ph_id)
    await ensure_feature(db, ph_id, Feature.INVENTORY_LITE)

Enforcement rules (locked with the product owner):
  - No active/valid subscription  → HTTP 402 (hard paywall).
  - Plan does not include feature  → HTTP 402 with an upgrade hint.
  - Expiry is **lazy** and has **no grace period**: a row whose
    ``current_period_end`` is in the past is treated as EXPIRED (and the
    status is opportunistically persisted), so no cron is needed.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import Feature, SubscriptionStatus
from models.subscription import Subscription


def _payment_required(message: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={"status_code": 402, "message": message, "data": None},
    )


async def get_active_subscription(
    db: AsyncSession, medical_store_id: int
) -> Subscription | None:
    """Return the store's live subscription, or ``None`` if it has no valid one.

    Lazily flips an otherwise-ACTIVE row to EXPIRED when its period has
    elapsed (committed opportunistically) so downstream reads are consistent.
    """
    result = await db.execute(
        select(Subscription)
        .where(Subscription.medical_store_id == medical_store_id)
        .order_by(Subscription.subscription_id.desc())
    )
    sub = result.scalars().first()
    if sub is None:
        return None

    if sub.status == SubscriptionStatus.ACTIVE.value:
        if sub.current_period_end is not None and sub.current_period_end < datetime.utcnow():
            sub.status = SubscriptionStatus.EXPIRED.value
            await db.commit()
            return None
        return sub

    return None


async def ensure_feature(
    db: AsyncSession, medical_store_id: int, feature: Feature
) -> Subscription:
    """Raise 402 unless the store has an active subscription granting ``feature``."""
    sub = await get_active_subscription(db, medical_store_id)
    if sub is None:
        _payment_required("No active subscription for this pharmacy")

    granted = sub.plan.features or [] if sub.plan is not None else []
    if feature.value not in granted:
        _payment_required(
            f"Your plan does not include {feature.value}. "
            "Upgrade your subscription to access this feature."
        )
    return sub


def within_limit(sub: Subscription, key: str, current_count: int) -> bool:
    """True if ``current_count`` is allowed under the plan's cap for ``key``.

    "Up to N" semantics: a count equal to the cap is allowed; only counts
    strictly greater than the cap are blocked. An absent key or an
    absent/empty ``limits`` dict means unlimited. Callers enforce and raise.
    """
    if sub.plan is None:
        return True
    limits = sub.plan.limits or {}
    cap = limits.get(key)
    if cap is None:
        return True
    return current_count <= cap


async def entitled_store_ids(
    db: AsyncSession, medical_store_ids: list[int], feature: Feature
) -> list[int]:
    """Filter ``medical_store_ids`` to those with an active subscription granting ``feature``.

    Used by cross-store list endpoints (which span many stores and can't call
    ``ensure_feature`` on a single id) to hide rows belonging to stores that
    aren't entitled to that feature. Expired/cancelled subscriptions are
    excluded (``current_period_end >= now`` and status ACTIVE).
    """
    if not medical_store_ids:
        return []
    now = datetime.utcnow()
    result = await db.execute(
        select(Subscription).where(
            Subscription.medical_store_id.in_(medical_store_ids),
            Subscription.status == SubscriptionStatus.ACTIVE.value,
            Subscription.current_period_end >= now,
        )
    )
    return [
        s.medical_store_id
        for s in result.scalars().all()
        if s.plan is not None and feature.value in (s.plan.features or [])
    ]
