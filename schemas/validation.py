"""
schemas/validation.py
─────────────────────
Strict Pydantic models for the validation engine. Used by the dispense
extraction route (Tier 1 embedded in `data.validation`), by
`POST /dispenses/validate` (Tier 1 + 2), and by `POST /dispenses` (422
detail when blocking errors are present).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["ERROR", "WARNING", "INFO", "INDETERMINATE", "PASS"]


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: Literal["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "FIELD", "INGEST"]
    code: str  # stable machine code, e.g. NDC_DISCONTINUED, DRUG_NAME_BLEED
    severity: Severity
    message: str
    medicine_index: int | None = None
    dispense_index: int | None = None
    ndc: str | None = None
    rx_no: str | None = None
    patient_key: str | None = None  # hashed; never raw PHI
    field: str | None = None
    expected: Any | None = None
    actual: Any | None = None
    suggestion: str | None = None


class GrandTotalRecompute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    printed_rx_count: int | None = None
    printed_total_price: str | None = None
    printed_total_cost: str | None = None
    recomputed_rx_count: int
    recomputed_sum_price: str
    recomputed_sum_ins_paid: str
    recomputed_sum_qty: str
    delta_rx_count: int | None = None
    delta_total_price: str | None = None


class PerPatientTotal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_key: str
    patient_label: str  # last-name initial + first initial — light de-id for UI
    insurance: str | None = None  # canonical ins_code — rows never blend differing insurance
    rx_count: int
    total_price: str
    total_ins_paid: str
    patient_responsibility: str


class ValidationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    errors: int = 0
    warnings: int = 0
    info: int = 0
    indeterminate: int = 0
    blocking: bool = False  # True iff errors > 0
    tier1_ran: bool = False
    tier2_ran: bool = False


class MedicineEnrichment(BaseModel):
    """FDA-verified manufacturer/strength/original pack size for one medicine,
    surfaced alongside (not replacing) the OCR-extracted values on
    `MedicineInput.manufacturer`/`.strength`/`.pack_size`."""

    model_config = ConfigDict(extra="forbid")
    medicine_index: int
    ndc: str
    found_in_fda: bool
    manufacturer: str | None = None        # FDA labeler_name
    strength: str | None = None            # FDA active_ingredients, joined
    original_pack_size: str | None = None  # e.g. "8.5 mL" / "120 SPRAY, METERED"
    dosage_form: str | None = None
    brand_name: str | None = None
    generic_name: str | None = None


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: ValidationSummary
    alerts: list[Alert]
    grand_total: GrandTotalRecompute | None = None
    per_patient: list[PerPatientTotal] = Field(default_factory=list)
    medicine_enrichment: list[MedicineEnrichment] = Field(default_factory=list)
