"""
schemas/pending_document.py
────────────────────────────
Lightweight placeholder for a `Document` that hasn't produced a saved
DrugReport/Invoice row yet. Used by the dispense-report and invoice list
endpoints to surface in-flight/failed/awaiting-review uploads alongside
already-saved rows. Does NOT embed `result_data` — the client fetches the
full extracted JSON via `GET /documents/{doc_key}` on demand.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PendingDocumentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: Literal["pending_document"] = "pending_document"
    doc_key: str
    state: Literal["PENDING", "AWAITING_REVIEW", "FAILED"]
    original_filename: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
