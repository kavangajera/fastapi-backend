"""
schemas/document_schemas.py
───────────────────────────
Pydantic request/response models for the /documents endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    """Response after successfully queuing a document for processing."""

    doc_key: str
    status: str
    message: str


class DocumentStatusResponse(BaseModel):
    """Full status view of a single document."""

    doc_key: str
    document_type: str
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    status: str
    retry_count: int
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    documents: list[DocumentStatusResponse]
    total: int
