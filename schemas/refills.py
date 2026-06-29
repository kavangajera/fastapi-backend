"""
schemas/refills.py
──────────────────
Response models for the refill-due list (`GET /pharmacy/{id}/refills`).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from schemas.audit_fields import AuditFields


class RefillRow(AuditFields):
    model_config = ConfigDict(extra="forbid")

    patient_key: str
    customer_name: str | None = None
    phone: str | None = None
    drug_name: str
    ndc: str
    last_qty: str | None = None
    days_supply: int | None = None
    last_fill_date: str | None = None
    next_due: date | None = None
    days_remaining: int | None = None
    status: str  # OVERDUE | DUE_SOON | OK | UNKNOWN


class RefillListResponse(AuditFields):
    model_config = ConfigDict(extra="forbid")

    medical_store_id: int
    items: list[RefillRow]
    total: int


class RefillDismissResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medical_store_id: int
    patient_key: str
    drug_ndc: str | None = None
    dismissed: bool
