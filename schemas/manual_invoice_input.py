"""
Pydantic schemas for **manual** invoice data entry via JSON.

Required fields per line item:
  - ndc11       (11-digit NDC)
  - invoiced_qty (quantity invoiced)

All other fields are optional, matching the Invoice / InvoiceLineItem / InvoiceSummary models.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Line-item input
# ---------------------------------------------------------------------------
class ManualInvoiceLineItemInput(BaseModel):
    """A single line item on an invoice — entered manually."""

    ndc11: str = Field(
        ...,
        min_length=11,
        max_length=11,
        description="11-digit NDC (required)",
        examples=["00093505601"],
    )
    invoiced_qty: str = Field(
        ...,
        min_length=1,
        description="Quantity invoiced (required)",
        examples=["100"],
    )

    # ── everything else is optional ──────────────────────────────────────
    line: Optional[str] = Field(None, description="Line number on the invoice")
    item_code: Optional[str] = None
    raw_ndc: Optional[str] = None
    upc: Optional[str] = None
    lot_number: Optional[str] = None
    orig_order_qty: Optional[str] = None
    order_qty: Optional[str] = None
    uom: Optional[str] = None
    description: Optional[str] = None
    size: Optional[str] = None
    form: Optional[str] = None
    unit_price: Optional[str] = None
    extended_price: Optional[str] = None
    awp: Optional[str] = None
    note_code: Optional[str] = None


# ---------------------------------------------------------------------------
# Summary input (optional block)
# ---------------------------------------------------------------------------
class ManualInvoiceSummaryInput(BaseModel):
    """Invoice-level totals — entirely optional."""

    order_line_total: Optional[str] = None
    fuel_surcharge: Optional[str] = None
    sub_total: Optional[str] = None
    tax: Optional[str] = None
    grand_total: Optional[str] = None
    total_due_by: Optional[str] = None


# ---------------------------------------------------------------------------
# Top-level invoice input
# ---------------------------------------------------------------------------
class ManualInvoiceInput(BaseModel):
    """
    Top-level payload for manually creating an invoice.

    Only ``line_items`` is required (with at least one entry).
    All header fields are optional.
    """

    # ── Seller info ──────────────────────────────────────────────────────
    seller_name: Optional[str] = None
    seller_address: Optional[str] = None
    seller_phone: Optional[str] = None
    seller_dea: Optional[str] = None
    seller_permit: Optional[str] = None
    seller_fed_id: Optional[str] = None

    # ── Invoice meta ─────────────────────────────────────────────────────
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    order_number: Optional[str] = None
    due_date: Optional[str] = None
    terms_of_payment: Optional[str] = None
    your_order_number: Optional[str] = None

    # ── Customer info ────────────────────────────────────────────────────
    customer_number: Optional[str] = None
    customer_name: Optional[str] = None
    customer_dea: Optional[str] = None
    customer_state_reg: Optional[str] = None

    # ── Addresses ────────────────────────────────────────────────────────
    bill_to_name: Optional[str] = None
    bill_to_address: Optional[str] = None
    ship_to_name: Optional[str] = None
    ship_to_address: Optional[str] = None
    remit_to_name: Optional[str] = None
    remit_to_address: Optional[str] = None
    remit_to_phone: Optional[str] = None

    # ── Line items (required) ────────────────────────────────────────────
    line_items: List[ManualInvoiceLineItemInput] = Field(
        ...,
        min_length=1,
        description="At least one line item is required.",
    )

    # ── Optional summary ─────────────────────────────────────────────────
    summary: Optional[ManualInvoiceSummaryInput] = None


# ---------------------------------------------------------------------------
# Output schema  (reuses existing InvoiceResponse for the full read-back)
# ---------------------------------------------------------------------------
class ManualInvoiceCreatedOutput(BaseModel):
    """Confirmation returned after a manual invoice is stored."""

    invoice_id: int
    line_items_created: int
    message: str = "Invoice created successfully via manual entry."
