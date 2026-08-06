"""
schemas/document_schemas.py
───────────────────────────
Pydantic request/response models for the /documents endpoints.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from schemas.audit_fields import AuditFields


class DocumentUploadResponse(BaseModel):
    """
    Response of the unified upload endpoint.

    On the async-await happy path the worker finishes within the timeout
    and `data` holds the processed result. On timeout, `status` is
    ``QUEUED`` with `data=None` and the caller can poll GET /documents/{doc_key}.
    """

    doc_key: str
    process_type: str
    status: str  # COMPLETED | FAILED_PERMANENTLY | QUEUED (timeout)
    message: str
    data: Any | None = None
    error: str | None = None


class DocumentStatusResponse(AuditFields):
    """Full status view of a single document."""

    doc_key: str
    document_type: str
    process_type: str
    original_filename: str | None = None
    file_size: int | None = None
    status: str
    retry_count: int
    error_message: str | None = None
    # Stored on the Document row as a JSON-encoded string (MEDIUMTEXT); parsed
    # here so the client can bind it straight into the save form (e.g.
    # DispenseSaveRequest/InvoiceSaveRequest) once state is AWAITING_REVIEW,
    # with no manual JSON.parse step.
    result_data: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("result_data", mode="before")
    @classmethod
    def _parse_result_data(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return None
        return value


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    documents: list[DocumentStatusResponse]
    total: int
