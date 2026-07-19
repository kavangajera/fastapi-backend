"""
models/subscription.py
──────────────────────
A pharmacy's subscription to a plan, plus an append-only audit trail of
subscription changes.

A subscription is mapped to a **medical_store** (pharmacy), not a user — an
owner may hold different plans per store. There is at most one *live* (non
soft-deleted) subscription per store; this is enforced in
``services/subscription_service.py`` rather than by a hard DB unique so that
soft-deleted history rows stay valid.

``current_period_end`` is the stored expiry the request asked for. Enforcement
is lazy: ``services/feature_gate.get_active_subscription`` treats a row whose
``current_period_end`` is in the past as EXPIRED (no grace period), so no cron
job is required.
"""

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.async_db import AuditMixin, Base


class Subscription(AuditMixin, Base):
    __tablename__ = "subscriptions"

    subscription_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )

    medical_store_id: Mapped[int] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.plan_id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # core.enums.SubscriptionStatus (stored as string value).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ACTIVE", index=True
    )

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    # The stored plan expiry — enforced lazily by the feature gate.
    current_period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    stripe_subscription_id = Column(String(255), nullable=True, unique=True, comment="Stripe Subscription ID")
    stripe_checkout_session_id = Column(String(255), nullable=True, comment="Pending Stripe Checkout Session")

    plan = relationship("Plan", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<Subscription(medical_store_id={self.medical_store_id}, "
            f"plan_id={self.plan_id}, status={self.status!r}, "
            f"ends={self.current_period_end})>"
        )


class SubscriptionEvent(AuditMixin, Base):
    """Append-only log of subscription changes (who did what, when)."""

    __tablename__ = "subscription_events"

    event_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.subscription_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # SUBSCRIBE / UPGRADE / DOWNGRADE / RENEW / REVOKE / ADMIN_MODIFY
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    from_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<SubscriptionEvent(sub={self.subscription_id}, action={self.action!r})>"
