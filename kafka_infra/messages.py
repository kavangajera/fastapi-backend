"""
kafka_infra/messages.py
───────────────────────
Pydantic models for Kafka message payloads.

Messages carry only metadata (doc_key, type, attempt) — never file
content. The file lives in storage; workers load it by doc_key.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProcessingJob(BaseModel):
    """A unit of work published to a ``<type>-processing`` topic."""

    doc_key: str
    process_type: str  # ProcessType value: dispense | invoice | barcode
    attempt: int = 1   # 1-based; incremented on each retry
    # ISO 8601 timestamp before which the retry consumer must NOT
    # re-inject this job into the main topic (delayed retry).
    process_after: Optional[str] = None
    enqueued_at: str = Field(default_factory=_utcnow_iso)

    @classmethod
    def create(cls, doc_key: str, process_type: str) -> "ProcessingJob":
        return cls(doc_key=doc_key, process_type=process_type, attempt=1)


class ProcessingResult(BaseModel):
    """
    Outcome published to the shared ``processing-results`` topic so the
    API can resolve the awaiting upload request (async-await UX).
    """

    doc_key: str
    process_type: str
    status: str  # DocumentStatus value: COMPLETED | FAILED_PERMANENTLY
    result_data: Optional[Any] = None
    error: Optional[str] = None
    retry_count: int = 0
    finished_at: str = Field(default_factory=_utcnow_iso)
