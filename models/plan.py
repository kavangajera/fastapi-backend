"""
models/plan.py
──────────────
Subscription plan catalog.

Each row is a purchasable tier (Essential / Automation Pro / Analytics Plus /
Unlimited Supreme). Pricing is stored in **cents** to avoid float money.

``features`` is the **entitlement source of truth** — a JSON list of
``core.enums.Feature`` values this plan unlocks. It lives on the row (not in
code) so an admin can adjust what a tier includes at runtime via
``POST/PUT /admin/plans`` without a redeploy.

``limits`` is an optional JSON dict of soft caps (e.g.
``{"drug_reconciliation_limit": 250}`` for Basic/Advanced). An empty/absent
dict means "unlimited" (Ultimate).
"""

from sqlalchemy import JSON, Boolean, Column, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from core.async_db import AuditMixin, Base


class Plan(AuditMixin, Base):
    __tablename__ = "plans"

    plan_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )

    # One of core.enums.PlanCode (stored as its string value).
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Ordering key for upgrade/downgrade comparison (1..4).
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    monthly_price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # JSON list of Feature values this plan grants (entitlement source of truth).
    features: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # JSON dict of soft caps; {} / null == unlimited.
    limits: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("1"), nullable=False
    )
    
    stripe_product_id = Column(String(255), nullable=True, comment="Stripe Product ID")
    stripe_price_id = Column(String(255), nullable=True, comment="Stripe Price ID (monthly recurring)")

    def __repr__(self) -> str:
        return f"<Plan(code={self.code!r}, tier={self.tier})>"
