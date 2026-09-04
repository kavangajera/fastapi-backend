"""
schemas/pharmacy_reset.py
─────────────────────────
Request/response models for `POST /pharmacy/{ph_id}/reset-data`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ResetDataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = Field(
        ...,
        description="Must be true — acknowledges this deletes all data for this pharmacy.",
    )


class ResetDataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pharmacy_id: int
    dispenses_deleted: int
    medicines_deleted: int
    drug_reports_deleted: int
    invoice_line_items_deleted: int
    invoice_summaries_deleted: int
    invoices_deleted: int
    inventory_rows_deleted: int
    documents_deleted: int
