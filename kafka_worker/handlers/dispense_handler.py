"""
kafka_worker/handlers/dispense_handler.py
─────────────────────────────────────────
Extraction-only dispense report handler + Tier-1 validation pass.

Tier-1 (`services/validation/tier1.py`) is pure-data and synchronous, so
we run it inline. Tier-2 (FDA-dependent) is intentionally deferred to
`/dispenses/validate` and `/dispenses` so per-NDC HTTP latency doesn't
blow past the result-bus timeout.
"""

from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from models.document import Document
from services.document_extractor import extract_report_from_file
from services.document_storage import document_storage
from services.validation import validate_tier1


async def handle_dispense(
    session: AsyncSession,
    doc: Document,
    *,
    medical_store_id: int,
) -> dict:
    file_bytes = document_storage.retrieve(doc.storage_path)
    filename = doc.original_filename or doc.doc_key

    logger.info(
        "Dispense extract: doc_key={dk} file={f}",
        dk=doc.doc_key,
        f=filename,
    )

    report_data = await asyncio.to_thread(extract_report_from_file, file_bytes, filename)
    report_data["medical_store_id"] = medical_store_id
    report_data["document_id"] = doc.id

    tier1 = validate_tier1(report_data)
    report_data["validation"] = tier1.model_dump(mode="json")
    logger.info(
        "Dispense Tier-1 validation: ms_id={p} doc_key={dk} errors={e} warnings={w} info={i}",
        p=medical_store_id,
        dk=doc.doc_key,
        e=tier1.summary.errors,
        w=tier1.summary.warnings,
        i=tier1.summary.info,
    )
    return report_data
