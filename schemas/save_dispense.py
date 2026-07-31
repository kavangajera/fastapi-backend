"""
schemas/save_dispense.py
────────────────────────
Strict Pydantic schemas for `POST /dispenses`.

Mirrors the dispense extractor's output shape (services/document_extractor).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)
    total_rx_count: str | int | None = None
    total_ins_paid: str | float | None = None
    total_price: str | float | None = None
    total_cost: str | float | None = None


class DispenseLineInput(AuditInputFields):
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)
    qty_disp: str | float | None = None
    qty_ord: str | float | None = None
    days_supply: str | int | float | None = None
    date_filled: str | None = None
    rx_no: str | None = None
    reference_number: str | None = None
    ref: str | int | None = None
    pat_name: str | None = None
    pat_addr: str | None = None
    pat_phone: str | None = None
    patient_dob: str | None = None
    patient_gender: str | None = None
    patient_id: str | None = None
    pres_name: str | None = None
    pres_addr: str | None = None
    pres_phone: str | None = None
    prescriber_dea: str | None = None
    prescriber_npi: str | None = None
    date_written: str | None = None
    date_sold: str | None = None
    will_call_date: str | None = None
    price: str | float | None = None
    ins_paid: str | float | None = None
    ins_code: str | None = None
    patient_copay: str | float | None = None
    cash_price: str | float | None = None
    total_price: str | float | None = None
    source_page: int | None = None
    is_partial: bool = False
    warnings: list[str] = Field(default_factory=list)
    # Extractor echoes these from the medicine row onto each dispense
    # entry; we accept-but-ignore them so the raw JSON round-trips.
    inventory_bucket: str | None = None
    lot_no_exp_date: str | None = None


class MedicineTotalsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)
    packs: str | float | None = None
    total_quantity_dispensed: str | float | None = None
    total_rx_count: str | int | None = None
    total_ins_paid: str | float | None = None
    total_price: str | float | None = None
    total_cost: str | float | None = None


class MedicineInput(AuditInputFields):
    model_config = ConfigDict(extra="forbid")
    drug_name: str
    ndc: str
    inventory_bucket: str | None = None
    lot_no_exp_date: str | None = None
    lot_number: str | None = None
    expiration_date: str | None = None
    pack_size: str | None = None
    manufacturer: str | None = None
    generic_indicator: str | None = None
    strength: str | None = None
    daw_code: str | None = None
    drug_schedule: str | None = None
    totals: MedicineTotalsInput | None = None
    dispenses: list[DispenseLineInput] = Field(default_factory=list)


class DispenseSaveRequest(AuditInputFields):
    model_config = ConfigDict(extra="forbid")
    medical_store_id: int
    document_id: int | None = None
    # Persist even when validation finds blocking (ERROR) alerts. The errors
    # are still recorded on the report and per-medicine row so the audit
    # report can surface them. Inventory is updated regardless.
    force_save: bool = False
    pharmacy: DispensePharmacyMeta = Field(default_factory=DispensePharmacyMeta)
    grand_total: DispenseGrandTotal = Field(default_factory=DispenseGrandTotal)
    medicines: list[MedicineInput]

    # `/documents/process` embeds Tier-1 validation results in the `data`
    # block it returns. The UI copies that whole block into this save
    # request; we accept-but-ignore — the save route re-validates from
    # scratch on every submit, so any embedded report is just a stale
    # echo of the prior run.
    validation: Any | None = None


class DispensePatchLineInput(BaseModel):
    """A single dispense line to patch — rx_no is the lookup key."""

    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)
    rx_no: str
    qty_disp: str | float | None = None
    qty_ord: str | float | None = None
    days_supply: str | int | float | None = None
    date_filled: str | None = None
    ref: str | int | None = None
    pat_name: str | None = None
    pat_addr: str | None = None
    pat_phone: str | None = None
    pres_name: str | None = None
    pres_addr: str | None = None
    pres_phone: str | None = None
    price: str | float | None = None
    ins_paid: str | float | None = None
    ins_code: str | None = None
    reference_number: str | None = None
    patient_dob: str | None = None
    patient_gender: str | None = None
    patient_id: str | None = None
    prescriber_dea: str | None = None
    prescriber_npi: str | None = None
    date_written: str | None = None
    date_sold: str | None = None
    will_call_date: str | None = None
    patient_copay: str | float | None = None
    cash_price: str | float | None = None
    total_price: str | float | None = None


class DispensePatchRequest(AuditInputFields):
    """Partial update: only the listed rx_no entries are touched."""

    model_config = ConfigDict(extra="forbid")
    medical_store_id: int
    dispenses: list[DispensePatchLineInput]


class DispenseSaveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: int
    pharmacy_id: int = Field(validation_alias="medical_store_id")
    medicines_saved: int
    dispenses_saved: int
    force_saved: bool = False
    medicines_with_errors: int = 0
    inventory_updates: list[InventoryUpdate]
    validation: ValidationReport
