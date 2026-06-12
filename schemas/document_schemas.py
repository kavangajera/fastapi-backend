"""
schemas/document_schemas.py
───────────────────────────
Pydantic request/response models for the /documents endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


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


class DocumentStatusResponse(BaseModel):
    """Full status view of a single document."""

    doc_key: str
    document_type: str
    process_type: str
    original_filename: str | None = None
    file_size: int | None = None
    status: str
    retry_count: int
    error_message: str | None = None
    result_data: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    documents: list[DocumentStatusResponse]
    total: int
