"""
Pydantic schemas for **manual** dispense (purchase-report) data entry via JSON.

Required fields:
  - Each medicine entry requires ``ndc11`` and ``drug_name``.
  - Each dispense entry requires ``qty_disp`` (quantity dispensed).

All other fields are optional, matching the DrugReport / Medicine / Dispense models.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Dispense-level input
# ---------------------------------------------------------------------------
class ManualDispenseItemInput(BaseModel):
    """A single prescription fill line — entered manually."""

    qty_disp: Decimal = Field(
        ...,
        description="Quantity dispensed (required)",
        examples=[30.0],
    )

    # ── everything else is optional ──────────────────────────────────────
    qty_ord: Decimal | None = None
    days_supply: int | None = None
    date_filled: str | None = Field(None, description="MM/DD/YYYY")
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


# ---------------------------------------------------------------------------
# Medicine-level input
# ---------------------------------------------------------------------------
class ManualMedicineInput(BaseModel):
    """A single medicine/NDC block with its dispense lines."""

    ndc11: str = Field(
        ...,
        min_length=11,
        max_length=11,
        description="11-digit NDC (required)",
        examples=["00093505601"],
    )
    drug_name: str | None = Field(
        "Unknown",
        description="Drug name (defaults to 'Unknown' if omitted)",
    )

    # ── optional drug-level fields ───────────────────────────────────────
    inventory_bucket: str | None = None
    lot_no_exp_date: str | None = None
    total_packs: Decimal | None = None
    total_rx_count: int | None = None
    total_ins_paid: Decimal | None = None
    total_price: Decimal | None = None
    total_cost: Decimal | None = None

    # ── dispense lines (at least one required) ───────────────────────────
    dispenses: list[ManualDispenseItemInput] = Field(
        ...,
        min_length=1,
        description="At least one dispense line is required per medicine.",
    )


# ---------------------------------------------------------------------------
# Top-level report input
# ---------------------------------------------------------------------------
class ManualDispenseReportInput(BaseModel):
    """
    Top-level payload for manually creating a dispense (purchase) report.

    Only ``medicines`` is required (with at least one entry).
    All header fields are optional.
    """

    # ── Pharmacy header ──────────────────────────────────────────────────
    pharmacy_name: str | None = None
    pharmacy_address: str | None = None
    pharmacy_phone: str | None = None
    pharmacy_fax: str | None = None

    # ── Report meta ──────────────────────────────────────────────────────
    report_date: str | None = None
    report_from_date: str | None = None
    report_to_date: str | None = None

    # ── Grand totals ─────────────────────────────────────────────────────
    grand_total_rx_count: int | None = None
    grand_total_price: Decimal | None = None
    grand_total_cost: Decimal | None = None

    # ── Medicines (required) ─────────────────────────────────────────────
    medicines: list[ManualMedicineInput] = Field(
        ...,
        min_length=1,
        description="At least one medicine entry is required.",
    )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------
class ManualDispenseReportCreatedOutput(BaseModel):
    """Confirmation returned after a manual dispense report is stored."""

    report_id: int
    medicines_created: int
    dispenses_created: int
    message: str = "Dispense report created successfully via manual entry."
