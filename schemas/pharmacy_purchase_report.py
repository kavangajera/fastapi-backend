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
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Dispense schemas
# ---------------------------------------------------------------------------
class DispenseBase(BaseModel):
    qty_disp: Optional[Decimal] = None
    qty_ord: Optional[Decimal] = None
    days_supply: Optional[int] = None
    date_filled: Optional[str] = None
    rx_no: Optional[str] = None
    ref: Optional[str] = None
    pat_name: Optional[str] = None
    pat_addr: Optional[str] = None
    pat_phone: Optional[str] = None
    pres_name: Optional[str] = None
    pres_addr: Optional[str] = None
    pres_phone: Optional[str] = None
    price: Optional[Decimal] = None
    ins_paid: Optional[Decimal] = None
    ins_code: Optional[str] = None


class DispenseResponse(DispenseBase):
    """Returned when reading a dispense from the DB."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    medicine_id: int


# ---------------------------------------------------------------------------
# Medicine schemas
# ---------------------------------------------------------------------------
class MedicineBase(BaseModel):
    drug_name: str
    ndc: str = Field(..., min_length=11, max_length=11, description="11-digit NDC")
    inventory_bucket: Optional[str] = None
    lot_no_exp_date: Optional[str] = None
    total_packs: Optional[Decimal] = None
    total_rx_count: Optional[int] = None
    total_ins_paid: Optional[Decimal] = None
    total_price: Optional[Decimal] = None
    total_cost: Optional[Decimal] = None


class MedicineResponse(MedicineBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_id: int
    dispenses: List[DispenseResponse] = []


# ---------------------------------------------------------------------------
# DrugReport schemas
# ---------------------------------------------------------------------------
class DrugReportBase(BaseModel):
    pharmacy_name: Optional[str] = None
    pharmacy_address: Optional[str] = None
    pharmacy_phone: Optional[str] = None
    pharmacy_fax: Optional[str] = None
    report_date: Optional[str] = None
    report_from_date: Optional[str] = None
    report_to_date: Optional[str] = None
    grand_total_rx_count: Optional[int] = None
    grand_total_price: Optional[Decimal] = None
    grand_total_cost: Optional[Decimal] = None


class DrugReportResponse(DrugReportBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    medicines: List[MedicineResponse] = []


# ---------------------------------------------------------------------------
# Upload / confirmation response
# ---------------------------------------------------------------------------
class UploadSummary(BaseModel):
    """Returned immediately after a successful PDF upload + DB insert."""

    report_id: int
    pharmacy_name: Optional[str]
    report_from_date: Optional[str]
    report_to_date: Optional[str]
    medicines_saved: int
    dispenses_saved: int
    grand_total_rx_count: Optional[int]
    grand_total_price: Optional[Decimal]
    message: str = "PDF processed and stored successfully."


class DrugReportListItem(BaseModel):
    """Lightweight summary for the list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    pharmacy_name: Optional[str]
    report_from_date: Optional[str]
    report_to_date: Optional[str]
    grand_total_rx_count: Optional[int]
    grand_total_price: Optional[Decimal]