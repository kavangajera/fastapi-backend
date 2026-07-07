"""
schemas/inventory.py
────────────────────
Strict response schemas for the inventory GET endpoints.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from schemas.audit_fields import AuditFields
from schemas.audit_input import AuditInputFields


class InventoryRow(AuditFields):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    code: str  # NDC (or UPC fallback)
    product_name: str | None = None
    quantity: str  # serialized Decimal — Total stack
    status: str  # derived stock status: In stock / Low stock / Out of stock
    location: str | None = None  # physical shelf/bin
    exp_date: str | None = None  # only set when a barcode/QR was scanned
    last_invoice_id: int | None = None
    updated_at: datetime | None = None


class InventoryDetail(AuditFields):
    """Single-item detail view (GET /pharmacy/{ph_id}/inventory/{code})."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    code: str  # NDC number
    product_name: str | None = None
    manufacturer: str | None = None  # medicine_ndc_cache.brand_name
    dosage_form: str | None = None  # Dose Form/Type
    lot_number: str | None = None  # latest invoice line item
    exp_date: str | None = None  # Expiry Date
    quantity: str  # Total stack
    status: str  # Stock Status
    location: str | None = None
    last_added: datetime | None = None  # Last Added (updated_at)


class InventoryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pharmacy_id: int = Field(validation_alias="medical_store_id")
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
    location: str | None = None
