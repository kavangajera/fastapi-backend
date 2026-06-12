from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.async_db import Base


# ---------------------------------------------------------------------------
# invoices
# ---------------------------------------------------------------------------
class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())

    medical_store_id: Mapped[int] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    seller_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    seller_address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    seller_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    seller_dea: Mapped[str | None] = mapped_column(String(40), nullable=True)
    seller_permit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    seller_fed_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    invoice_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    invoice_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    order_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    terms_of_payment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    your_order_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    customer_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_dea: Mapped[str | None] = mapped_column(String(40), nullable=True)
    customer_state_reg: Mapped[str | None] = mapped_column(String(40), nullable=True)

    bill_to_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bill_to_address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ship_to_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ship_to_address: Mapped[str | None] = mapped_column(String(400), nullable=True)

    remit_to_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    remit_to_address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    remit_to_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)

    raw_payload: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)

    line_items: Mapped[list["InvoiceLineItem"]] = relationship(
        "InvoiceLineItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    summary: Mapped[Optional["InvoiceSummary"]] = relationship(
        "InvoiceSummary",
        back_populates="invoice",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )


# ---------------------------------------------------------------------------
# invoice_line_items
# ---------------------------------------------------------------------------
class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )

    line: Mapped[str | None] = mapped_column(String(20), nullable=True)
    item_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw_ndc: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ndc11: Mapped[str | None] = mapped_column(String(11), nullable=True, index=True)
    upc: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    lot_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    orig_order_qty: Mapped[str | None] = mapped_column(String(30), nullable=True)
    order_qty: Mapped[str | None] = mapped_column(String(30), nullable=True)
    invoiced_qty: Mapped[str | None] = mapped_column(String(30), nullable=True)
    uom: Mapped[str | None] = mapped_column(String(10), nullable=True)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    size: Mapped[str | None] = mapped_column(String(40), nullable=True)
    form: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_price: Mapped[str | None] = mapped_column(String(30), nullable=True)
    extended_price: Mapped[str | None] = mapped_column(String(30), nullable=True)
    awp: Mapped[str | None] = mapped_column(String(30), nullable=True)
    note_code: Mapped[str | None] = mapped_column(String(30), nullable=True)

    verification_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fda_package_ndc: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fda_ndc11: Mapped[str | None] = mapped_column(String(11), nullable=True)

    dm_gtin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    dm_serial_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    dm_expiration_date: Mapped[str | None] = mapped_column(String(12), nullable=True)
    dm_lot_number: Mapped[str | None] = mapped_column(String(30), nullable=True)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="line_items")


# ---------------------------------------------------------------------------
# invoice_summaries
# ---------------------------------------------------------------------------
class InvoiceSummary(Base):
    __tablename__ = "invoice_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    order_line_total: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fuel_surcharge: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sub_total: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tax: Mapped[str | None] = mapped_column(String(30), nullable=True)
    grand_total: Mapped[str | None] = mapped_column(String(30), nullable=True)
    total_due_by: Mapped[str | None] = mapped_column(String(30), nullable=True)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="summary")
