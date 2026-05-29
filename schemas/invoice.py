from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class InvoiceLineItemBase(BaseModel):
    line: Optional[str] = None
    item_code: Optional[str] = None
    raw_ndc: Optional[str] = None
    ndc11: Optional[str] = None
    upc: Optional[str] = None
    lot_number: Optional[str] = None
    orig_order_qty: Optional[str] = None
    order_qty: Optional[str] = None
    invoiced_qty: Optional[str] = None
    uom: Optional[str] = None
    description: Optional[str] = None
    size: Optional[str] = None
    form: Optional[str] = None
    unit_price: Optional[str] = None
    extended_price: Optional[str] = None
    awp: Optional[str] = None
    note_code: Optional[str] = None

    verification_required: bool = True
    verified: bool = False
    fda_package_ndc: Optional[str] = None
    fda_ndc11: Optional[str] = None

    dm_gtin: Optional[str] = None
    dm_serial_number: Optional[str] = None
    dm_expiration_date: Optional[str] = None
    dm_lot_number: Optional[str] = None


class InvoiceLineItemResponse(InvoiceLineItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int


class InvoiceSummaryBase(BaseModel):
    order_line_total: Optional[str] = None
    fuel_surcharge: Optional[str] = None
    sub_total: Optional[str] = None
    tax: Optional[str] = None
    grand_total: Optional[str] = None
    total_due_by: Optional[str] = None


class InvoiceSummaryResponse(InvoiceSummaryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int


class InvoiceBase(BaseModel):
    source_filename: Optional[str] = None
    page_count: Optional[int] = None

    seller_name: Optional[str] = None
    seller_address: Optional[str] = None
    seller_phone: Optional[str] = None
    seller_dea: Optional[str] = None
    seller_permit: Optional[str] = None
    seller_fed_id: Optional[str] = None

    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    order_number: Optional[str] = None
    due_date: Optional[str] = None
    terms_of_payment: Optional[str] = None
    your_order_number: Optional[str] = None

    customer_number: Optional[str] = None
    customer_name: Optional[str] = None
    customer_dea: Optional[str] = None
    customer_state_reg: Optional[str] = None

    bill_to_name: Optional[str] = None
    bill_to_address: Optional[str] = None
    ship_to_name: Optional[str] = None
    ship_to_address: Optional[str] = None

    remit_to_name: Optional[str] = None
    remit_to_address: Optional[str] = None
    remit_to_phone: Optional[str] = None


class InvoiceResponse(InvoiceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    line_items: List[InvoiceLineItemResponse] = []
    summary: Optional[InvoiceSummaryResponse] = None


class InvoiceUploadSummary(BaseModel):
    invoices_created: int
    line_items_created: int
    message: str = "Invoices processed and stored successfully."
