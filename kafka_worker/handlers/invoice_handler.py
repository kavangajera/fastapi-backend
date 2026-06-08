"""
kafka_worker/handlers/invoice_handler.py
────────────────────────────────────────
Invoice processing: PDF → LLM extraction → persisted invoice.

Reuses the existing service layer:
    services.invoice_service.extract_invoice_from_pdf / store_invoice
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from models.document import Document
from services.document_storage import document_storage
from services.invoice_service import (
    count_pdf_pages,
    extract_invoice_from_pdf,
    store_invoice,
)


def handle_invoice(db: Session, doc: Document) -> dict:
    """Extract and store an invoice from the uploaded PDF."""
    file_bytes = document_storage.retrieve(doc.storage_path)
    filename = doc.original_filename or f"{doc.doc_key}.pdf"

    page_count = count_pdf_pages(file_bytes)
    logger.info(
        "Invoice processing: doc_key={doc_key} file={filename} pages={pages}",
        doc_key=doc.doc_key,
        filename=filename,
        pages=page_count,
    )

    invoice_payload = extract_invoice_from_pdf(file_bytes, filename)
    db_invoice = store_invoice(db, invoice_payload, filename, page_count)
    db.commit()

    return {
        "invoice_id": db_invoice.id,
        "line_items_created": len(invoice_payload.line_items),
        "page_count": page_count,
        "filename": filename,
    }
