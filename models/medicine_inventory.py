"""
models/medicine_inventory.py
────────────────────────────
Running inventory ledger keyed by (medical_store_id, code).

Two invoices for the same medicine merge into a single row whose
`quantity` accumulates. Each dispense report subtracts the dispensed
quantity from the matching row. The UNIQUE constraint backs the
`INSERT ... ON DUPLICATE KEY UPDATE` upsert used by
`services/inventory_service.py`.

`code` is either:
    - an 11-digit NDC (preferred, what FDA / dispense reports use), or
    - a UPC fallback for invoice lines we can't normalize to NDC11.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.async_db import AuditMixin, Base


class MedicineInventory(AuditMixin, Base):
    __tablename__ = "medicine_inventory"

    __table_args__ = (UniqueConstraint("medical_store_id", "code", name="uq_inventory_store_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    medical_store_id: Mapped[int] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    product_name: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Expiry shown in the UI ONLY when it came from a scanned barcode/QR
    # (InvoiceLineItem.dm_expiration_date). NULL when never scanned.
    exp_date: Mapped[str | None] = mapped_column(String(12), nullable=True)

    # Signed Decimal — quantity can go negative when dispense outpaces
    # known invoices. The save routes never reject; the UI surfaces it.
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal("0"), server_default="0"
    )

    last_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
