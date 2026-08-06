"""
services/pending_documents.py
──────────────────────────────
Shared logic for surfacing not-yet-saved `Document` rows in the dispense
report and invoice list endpoints (routes/pharmacy_purchase_report.py,
routes/invoice.py). A Document only disappears from these lists once a
matching DrugReport/Invoice row exists (linked via `document_id`).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import DocumentStatus
from models.document import Document

# Document.status -> small user-facing state surfaced in list responses.
_PENDING_STATE_MAP: dict[str, str] = {
    DocumentStatus.UPLOADED.value: "PENDING",
    DocumentStatus.QUEUED.value: "PENDING",
    DocumentStatus.PROCESSING.value: "PENDING",
    DocumentStatus.COMPLETED.value: "AWAITING_REVIEW",
    DocumentStatus.FAILED.value: "FAILED",
    DocumentStatus.RETRYING.value: "FAILED",
    DocumentStatus.FAILED_PERMANENTLY.value: "FAILED",
}

# All statuses this feature surfaces (i.e. every status a Document can hold).
RELEVANT_STATUSES: tuple[str, ...] = tuple(_PENDING_STATE_MAP)


def document_pending_state(status: str) -> str:
    """Map a raw Document.status to the small state exposed in list responses."""
    return _PENDING_STATE_MAP.get(status, "PENDING")


async def fetch_pending_documents(
    db: AsyncSession,
    *,
    process_type: str,
    medical_store_ids: list[int],
    saved_model,
) -> list[Document]:
    """Return Document rows for `process_type` that are either still
    in-flight, failed, or completed-but-not-yet-saved, scoped to
    `medical_store_ids`.

    `saved_model` is `DrugReport` or `Invoice` — both expose a
    `document_id` FK back to `documents.id`. Excludes any Document already
    referenced by a saved row, which is what prevents duplicate rows once
    the user saves.
    """
    if not medical_store_ids:
        return []

    not_saved = ~(
        select(saved_model.id).where(saved_model.document_id == Document.id).exists()
    )

    stmt = (
        select(Document)
        .where(
            Document.process_type == process_type,
            Document.medical_store_id.in_(medical_store_ids),
            Document.status.in_(RELEVANT_STATUSES),
            not_saved,
        )
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
