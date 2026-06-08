"""
schemas/document_schemas.py
───────────────────────────
Pydantic request/response models for the /documents endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

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
    status: str            # COMPLETED | FAILED_PERMANENTLY | QUEUED (timeout)
    message: str
    data: Optional[Any] = None
    error: Optional[str] = None


class DocumentStatusResponse(BaseModel):
    """Full status view of a single document."""

    doc_key: str
    document_type: str
    process_type: str
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    status: str
    retry_count: int
    error_message: Optional[str] = None
    result_data: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    documents: list[DocumentStatusResponse]
    total: int
