"""
models/activity_log.py
──────────────────────
Append-only audit trail of everything the owner / technician does that
matters: documents uploaded, dispense reports saved (or force-saved with
errors), invoices saved, inventory adjusted, refill customers dismissed.

This is the spine for two read surfaces:
    - `GET /pharmacy/{id}/activity`      (the operational feed, with filters)
    - `GET /pharmacy/{id}/audit-report`  (the audit / error view)

Denormalized `customer_name`, `wholesaler_name`, and `search_blob` are
written at log time so the activity feed can filter by customer / supplier /
medicine with plain indexed `WHERE ... LIKE` queries instead of joining
back into the domain tables on every read.

Rows are never updated or deleted by the app (CASCADE on store delete only).
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.async_db import Base


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )

    medical_store_id: Mapped[int] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL"), nullable=True
    )
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Stable machine code, e.g. DOCUMENT_UPLOADED, DISPENSE_FORCE_SAVED.
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    entity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Denormalized filter columns.
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    wholesaler_name: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    # Drug names + NDCs concatenated — backs the `medicine` LIKE filter.
    search_blob: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_errors: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Counts, totals, drug list, etc. for the feed detail view.
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ActivityLog id={self.id} action={self.action!r} "
            f"ms_id={self.medical_store_id} entity={self.entity_type}:{self.entity_id}>"
        )
