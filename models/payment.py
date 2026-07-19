"""
models/payment.py
─────────────────
Subscription payment tracking — one row per Stripe invoice/charge.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from core.async_db import AuditMixin, Base


class SubscriptionPayment(AuditMixin, Base):
    """Tracks individual payment events (invoices) from Stripe."""

    __tablename__ = "subscription_payments"

    payment_id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    subscription_id = Column(
        Integer,
        ForeignKey("subscriptions.subscription_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    medical_store_id = Column(
        Integer,
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stripe_payment_intent_id = Column(String(255), nullable=True, unique=True)
    stripe_invoice_id = Column(String(255), nullable=True)
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String(10), nullable=False, default="usd")
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    paid_at = Column(DateTime, nullable=True)
    failure_reason = Column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_subpay_ms_id_status", "medical_store_id", "status"),
    )
