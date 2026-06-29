"""
schemas/inventory.py
────────────────────
Strict response schemas for the inventory GET endpoints.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from schemas.audit_fields import AuditFields
from schemas.audit_input import AuditInputFields


class InventoryRow(AuditFields):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    code: str
    product_name: str | None = None
    quantity: str  # serialized Decimal
    exp_date: str | None = None  # only set when a barcode/QR was scanned
    last_invoice_id: int | None = None
    updated_at: datetime | None = None


class InventoryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medical_store_id: int
    items: list[InventoryRow]
    total: int
    skip: int = 0
    limit: int = 0


class InventoryAdjustRequest(AuditInputFields):
    model_config = ConfigDict(extra="forbid")

    # All optional — only provided fields are changed. `quantity` is an
    # absolute correction (SET), not a delta.
    product_name: str | None = None
    quantity: str | None = None
    exp_date: str | None = None
