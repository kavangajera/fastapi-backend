"""
Pydantic schemas for **manual** invoice data entry via JSON.

Required fields per line item:
  - ndc11       (11-digit NDC)
  - invoiced_qty (quantity invoiced)

All other fields are optional, matching the Invoice / InvoiceLineItem / InvoiceSummary models.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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
    line: str | None = Field(None, description="Line number on the invoice")
    item_code: str | None = None
    raw_ndc: str | None = None
    upc: str | None = None
    lot_number: str | None = None
    orig_order_qty: str | None = None
    order_qty: str | None = None
    uom: str | None = None
    description: str | None = None
    size: str | None = None
    form: str | None = None
    unit_price: str | None = None
    extended_price: str | None = None
    awp: str | None = None
    note_code: str | None = None

    # ── verification / FDA fields ────────────────────────────────────────
    verification_required: bool = Field(
        True, description="Whether barcode verification is required"
    )
    verified: bool = Field(False, description="Whether the item has been verified")
    fda_package_ndc: str | None = None
    fda_ndc11: str | None = None

    # ── DataMatrix barcode fields ────────────────────────────────────────
    dm_gtin: str | None = None
    dm_serial_number: str | None = None
    dm_expiration_date: str | None = None
    dm_lot_number: str | None = None


# ---------------------------------------------------------------------------
# Summary input (optional block)
# ---------------------------------------------------------------------------
class ManualInvoiceSummaryInput(BaseModel):
    """Invoice-level totals — entirely optional."""

    order_line_total: str | None = None
    fuel_surcharge: str | None = None
    sub_total: str | None = None
    tax: str | None = None
    grand_total: str | None = None
    total_due_by: str | None = None


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
    seller_name: str | None = None
    seller_address: str | None = None
    seller_phone: str | None = None
    seller_dea: str | None = None
    seller_permit: str | None = None
    seller_fed_id: str | None = None

    # ── Invoice meta ─────────────────────────────────────────────────────
    invoice_number: str | None = None
    invoice_date: str | None = None
    order_number: str | None = None
    due_date: str | None = None
    terms_of_payment: str | None = None
    your_order_number: str | None = None

    # ── Customer info ────────────────────────────────────────────────────
    customer_number: str | None = None
    customer_name: str | None = None
    customer_dea: str | None = None
    customer_state_reg: str | None = None

    # ── Addresses ────────────────────────────────────────────────────────
    bill_to_name: str | None = None
    bill_to_address: str | None = None
    ship_to_name: str | None = None
    ship_to_address: str | None = None
    remit_to_name: str | None = None
    remit_to_address: str | None = None
    remit_to_phone: str | None = None

    # ── Line items (required) ────────────────────────────────────────────
    line_items: list[ManualInvoiceLineItemInput] = Field(
        ...,
        min_length=1,
        description="At least one line item is required.",
    )

    # ── Optional summary ─────────────────────────────────────────────────
    summary: ManualInvoiceSummaryInput | None = None


# ---------------------------------------------------------------------------
# Output schema  (reuses existing InvoiceResponse for the full read-back)
# ---------------------------------------------------------------------------
class ManualInvoiceCreatedOutput(BaseModel):
    """Confirmation returned after a manual invoice is stored."""

    invoice_id: int
    line_items_created: int
    message: str = "Invoice created successfully via manual entry."
