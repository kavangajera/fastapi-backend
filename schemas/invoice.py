from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from schemas.audit_fields import AuditFields


class InvoiceLineItemBase(BaseModel):
    line: str | None = None
    item_code: str | None = None
    raw_ndc: str | None = None
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

    verification_required: bool = True
    verified: bool = False
    fda_package_ndc: str | None = None
    fda_ndc11: str | None = None

    dm_gtin: str | None = None
    dm_serial_number: str | None = None
    dm_expiration_date: str | None = None
    dm_lot_number: str | None = None


class InvoiceLineItemResponse(InvoiceLineItemBase, AuditFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int


class InvoiceSummaryBase(BaseModel):
    order_line_total: str | None = None
    fuel_surcharge: str | None = None
    sub_total: str | None = None
    tax: str | None = None
    grand_total: str | None = None
    total_due_by: str | None = None


class InvoiceSummaryResponse(InvoiceSummaryBase, AuditFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int


class InvoiceBase(BaseModel):
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


class InvoiceResponse(InvoiceBase, AuditFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    line_items: list[InvoiceLineItemResponse] = []
    summary: InvoiceSummaryResponse | None = None


class InvoiceUploadSummary(BaseModel):
    invoices_created: int
    line_items_created: int
    message: str = "Invoices processed and stored successfully."
