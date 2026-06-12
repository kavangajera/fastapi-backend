"""
kafka_infra/messages.py
───────────────────────
Pydantic models for Kafka message payloads.

Messages carry only metadata (doc_key, type, attempt, medical_store_id)
— never file content. The file lives in storage; workers load it by
doc_key. No batch concept in this flow.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProcessingJob(BaseModel):
    """A unit of work published to a ``<type>-processing`` topic."""

    doc_key: str
    process_type: str  # ProcessType value: dispense | invoice | barcode
    medical_store_id: int
    attempt: int = 1
    process_after: str | None = None
    enqueued_at: str = Field(default_factory=_utcnow_iso)

    @classmethod
    def create(
        cls,
        doc_key: str,
        process_type: str,
        medical_store_id: int,
    ) -> ProcessingJob:
        return cls(
            doc_key=doc_key,
            process_type=process_type,
            medical_store_id=medical_store_id,
            attempt=1,
        )


class ProcessingResult(BaseModel):
    """
    Outcome published to the shared ``processing-results`` topic so the
    API can resolve the awaiting upload request (async-await UX).
    """

    doc_key: str
    process_type: str
    medical_store_id: int | None = None
    status: str  # DocumentStatus value: COMPLETED | FAILED_PERMANENTLY
    result_data: Any | None = None
    error: str | None = None
    retry_count: int = 0
    finished_at: str = Field(default_factory=_utcnow_iso)
