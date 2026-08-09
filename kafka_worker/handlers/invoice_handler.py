"""
kafka_worker/handlers/invoice_handler.py
────────────────────────────────────────
Extraction-only invoice handler.

Reads the uploaded PDF, runs `services.invoice_service.extract_invoice_from_pdf`
in a thread, and returns the parsed `pydantic.model_dump()` dict. The
worker stashes this dict on `Document.result_data` and publishes it
through the result bus. Persistence into `invoices` / `invoice_line_items`
/ `invoice_summaries` is the responsibility of `POST /invoices` (route).
"""

from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from kafka_worker.errors import PermanentDocumentError
from models.document import Document
from services.document_storage import document_storage
from services.extraction_errors import NoExtractableDataError
from services.invoice_service import count_pdf_pages, extract_invoice_from_pdf


async def handle_invoice(
    session: AsyncSession,
    doc: Document,
    *,
    medical_store_id: int,
) -> dict:
    file_bytes = document_storage.retrieve(doc.storage_path)
    filename = doc.original_filename or f"{doc.doc_key}.pdf"

    page_count = await asyncio.to_thread(count_pdf_pages, file_bytes)
    logger.info(
        "Invoice extract: doc_key={dk} file={f} pages={p}",
        dk=doc.doc_key,
        f=filename,
        p=page_count,
    )

    try:
        invoice_payload = await asyncio.to_thread(extract_invoice_from_pdf, file_bytes, filename)
    except NoExtractableDataError as exc:
        # Every page was checked and none had usable data — retrying won't
        # help, this file isn't an invoice.
        raise PermanentDocumentError(422, str(exc)) from exc
    payload_dict = invoice_payload.model_dump()
    payload_dict["medical_store_id"] = medical_store_id
    payload_dict["source_filename"] = filename
    payload_dict["page_count"] = page_count
    payload_dict["document_id"] = doc.id
    return payload_dict
