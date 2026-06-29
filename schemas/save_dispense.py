"""
schemas/save_dispense.py
────────────────────────
Strict Pydantic schemas for `POST /dispenses`.

Mirrors the dispense extractor's output shape (services/document_extractor).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from schemas.audit_input import AuditInputFields
from schemas.save_invoice import InventoryUpdate
from schemas.validation import ValidationReport


class DispensePharmacyMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pharmacy_name: str | None = None
    address: str | None = None
    phone: str | None = None
    fax: str | None = None
    report_date: str | None = None
    report_from_date: str | None = None
    report_to_date: str | None = None


class DispenseGrandTotal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_rx_count: str | int | None = None
    total_price: str | None = None
    total_cost: str | None = None


class DispenseLineInput(AuditInputFields):
    model_config = ConfigDict(extra="forbid")
    qty_disp: str | None = None
    qty_ord: str | None = None
    days_supply: str | int | None = None
    date_filled: str | None = None
    rx_no: str | None = None
    ref: str | None = None
    pat_name: str | None = None
    pat_addr: str | None = None
    pat_phone: str | None = None
    pres_name: str | None = None
    pres_addr: str | None = None
    pres_phone: str | None = None
    price: str | None = None
    ins_paid: str | None = None
    ins_code: str | None = None
    # Extractor echoes these from the medicine row onto each dispense
    # entry; we accept-but-ignore them so the raw JSON round-trips.
    inventory_bucket: str | None = None
    lot_no_exp_date: str | None = None


class MedicineTotalsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    packs: str | None = None
    total_rx_count: str | int | None = None
    total_ins_paid: str | None = None
    total_price: str | None = None
    total_cost: str | None = None


class MedicineInput(AuditInputFields):
    model_config = ConfigDict(extra="forbid")
    drug_name: str
    ndc: str
    inventory_bucket: str | None = None
    lot_no_exp_date: str | None = None
    totals: MedicineTotalsInput | None = None
    dispenses: list[DispenseLineInput] = []


class DispenseSaveRequest(AuditInputFields):
    model_config = ConfigDict(extra="forbid")
    medical_store_id: int
    document_id: int | None = None
    # Persist even when validation finds blocking (ERROR) alerts. The errors
    # are still recorded on the report and per-medicine row so the audit
    # report can surface them. Inventory is updated regardless.
    force_save: bool = False
    pharmacy: DispensePharmacyMeta = DispensePharmacyMeta()
    grand_total: DispenseGrandTotal = DispenseGrandTotal()
    medicines: list[MedicineInput]

    # `/documents/process` embeds Tier-1 validation results in the `data`
    # block it returns. The UI copies that whole block into this save
    # request; we accept-but-ignore — the save route re-validates from
    # scratch on every submit, so any embedded report is just a stale
    # echo of the prior run.
    validation: Any | None = None


class DispenseSaveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: int
    medical_store_id: int
    medicines_saved: int
    dispenses_saved: int
    force_saved: bool = False
    medicines_with_errors: int = 0
    inventory_updates: list[InventoryUpdate]
    validation: ValidationReport
