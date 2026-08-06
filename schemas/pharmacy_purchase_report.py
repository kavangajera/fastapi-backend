"""
Pydantic v2 schemas for the Drug Dispensed Report API.

Response hierarchy mirrors the DB models:
  DrugReportResponse
    └── MedicineResponse[]
          └── DispenseResponse[]
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.audit_fields import AuditFields


# ---------------------------------------------------------------------------
# Dispense schemas
# ---------------------------------------------------------------------------
class DispenseBase(BaseModel):
    qty_disp: Decimal | None = None
    qty_ord: Decimal | None = None
    days_supply: int | None = None
    date_filled: str | None = None
    rx_no: str | None = None
    ref: str | None = None
    pat_name: str | None = None
    pat_addr: str | None = None
    pat_phone: str | None = None
    pres_name: str | None = None
    pres_addr: str | None = None
    pres_phone: str | None = None
    price: Decimal | None = None
    ins_paid: Decimal | None = None
    ins_code: str | None = None


class DispenseResponse(DispenseBase, AuditFields):
    model_config = ConfigDict(from_attributes=True)

    dispense_id: int = Field(validation_alias="id")
    medicine_id: int


# ---------------------------------------------------------------------------
# Medicine schemas
# ---------------------------------------------------------------------------
class MedicineBase(BaseModel):
    drug_name: str
    ndc: str = Field(..., min_length=11, max_length=11, description="11-digit NDC")
    inventory_bucket: str | None = None
    lot_no_exp_date: str | None = None
    total_packs: Decimal | None = None
    total_rx_count: int | None = None
    total_ins_paid: Decimal | None = None
    total_price: Decimal | None = None
    total_cost: Decimal | None = None


class MedicineResponse(MedicineBase, AuditFields):
    model_config = ConfigDict(from_attributes=True)

    medicine_id: int = Field(validation_alias="id")
    report_id: int
    dispenses: list[DispenseResponse] = []


# ---------------------------------------------------------------------------
# DrugReport schemas
# ---------------------------------------------------------------------------
class DrugReportBase(BaseModel):
    pharmacy_id: int = Field(validation_alias="medical_store_id")
    document_id: int | None = None
    batch_id: int | None = None
    report_date: str | None = None
    report_from_date: str | None = None
    report_to_date: str | None = None
    grand_total_rx_count: int | None = None
    grand_total_price: Decimal | None = None
    grand_total_cost: Decimal | None = None


class DrugReportResponse(DrugReportBase, AuditFields):
    model_config = ConfigDict(from_attributes=True)

    report_id: int = Field(validation_alias="id")
    created_at: datetime
    medicines: list[MedicineResponse] = []


class DrugReportListItem(AuditFields):
    """Lightweight summary for the list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    report_id: int = Field(validation_alias="id")
    created_at: datetime
    pharmacy_id: int = Field(validation_alias="medical_store_id")
    batch_id: int | None = None
    report_from_date: str | None
    report_to_date: str | None
    grand_total_rx_count: int | None
    grand_total_price: Decimal | None


class DrugReportListItemWrapped(DrugReportListItem):
    """`DrugReportListItem` tagged for the discriminated union used by
    `GET /reports/`, which also surfaces pending Document placeholders."""

    kind: Literal["drug_report"] = "drug_report"
