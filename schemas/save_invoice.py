"""
schemas/save_invoice.py
───────────────────────
Strict Pydantic schemas for `POST /invoices`.

The shape mirrors the extractor's output so a user can copy the
`/documents/process?process_type=invoice` response, optionally splice
per-line-item `fda_*` / `dm_*` fields from a barcode scan, and POST it.

`extra="forbid"` on every model — extra fields rejected with 422.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class InvoiceLineItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line: str | None = None
    item_code: str | None = None
    raw_ndc: str | None = None
    ndc: str | None = None  # extractor's raw 'ndc' field; route maps it
    ndc11: str | None = None
    upc: str | None = None
    lot_number: str | None = None
    orig_order_qty: str | None = None
    order_qty: str | None = None
    invoiced_qty: str | None = None
    uom: str | None = None
    description: str | None = None
    size: str | None = None
    form: str | None = None
    unit_price: str | None = None
    extended_price: str | None = None
    awp: str | None = None
    note_code: str | None = None

    # Optional barcode + datamatrix bundle. Merged into the line item
    # at persist time; UI copies these in from
    # `/documents/process?process_type=barcode` output.
    fda_package_ndc: str | None = None
    fda_ndc11: str | None = None
    dm_gtin: str | None = None
    dm_serial_number: str | None = None
    dm_expiration_date: str | None = None
    dm_lot_number: str | None = None
    verified: bool | None = None


class InvoiceSummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_line_total: str | None = None
    fuel_surcharge: str | None = None
    sub_total: str | None = None
    tax: str | None = None
    grand_total: str | None = None
    total_due_by: str | None = None


class InvoiceSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medical_store_id: int
    document_id: int | None = None
    source_filename: str | None = None
    page_count: int | None = None

    seller_name: str | None = None
    seller_address: str | None = None
    seller_phone: str | None = None
    seller_dea: str | None = None
    seller_permit: str | None = None
    seller_fed_id: str | None = None

    invoice_number: str | None = None
    invoice_date: str | None = None
    order_number: str | None = None
    due_date: str | None = None
    terms_of_payment: str | None = None
    your_order_number: str | None = None

    customer_number: str | None = None
    customer_name: str | None = None
    customer_dea: str | None = None
    customer_state_reg: str | None = None

    bill_to_name: str | None = None
    bill_to_address: str | None = None
    ship_to_name: str | None = None
    ship_to_address: str | None = None

    remit_to_name: str | None = None
    remit_to_address: str | None = None
    remit_to_phone: str | None = None

    line_items: list[InvoiceLineItemInput]
    summary: InvoiceSummaryInput | None = None


class InventoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    delta: str
    new_quantity: str


class InvoiceSaveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: int
    medical_store_id: int
    line_items_created: int
    summary_saved: bool
    inventory_updates: list[InventoryUpdate]
