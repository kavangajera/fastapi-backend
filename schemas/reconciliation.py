"""
schemas/reconciliation.py
─────────────────────────
Response models for invoice-vs-billed cross-reconciliation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReconciliationRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ndc: str
    drug_name: str | None = None
    invoiced_qty: str   # total purchased (from invoices)
    dispensed_qty: str  # total billed out (from dispense reports)
    delta: str          # dispensed − invoiced (positive = billed more than bought)
    status: str         # MATCHED / OVER_BILLED / UNDER_DISPENSED


class ReconciliationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ndc_count: int
    over_billed: int
    under_dispensed: int
    matched: int


class ReconciliationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pharmacy_id: int = Field(validation_alias="medical_store_id")
    summary: ReconciliationSummary
    items: list[ReconciliationRow]
    total: int
    skip: int
    limit: int
