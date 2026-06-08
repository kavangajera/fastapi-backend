"""
kafka_worker/handlers/dispense_handler.py
─────────────────────────────────────────
Dispense report processing: PDF/DOCX/DOC/XLSX/XLS → extraction →
persisted DrugReport + Medicines + Dispenses + Reconciliation.

Reuses:
    services.document_extractor.extract_report_from_file  (extraction)
    services.report_service.store_report                  (persistence)
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from models.document import Document
from services.document_storage import document_storage
from services.document_extractor import extract_report_from_file
from services.report_service import store_report


def handle_dispense(db: Session, doc: Document) -> dict:
    """Extract and store a dispense report from the uploaded document."""
    file_bytes = document_storage.retrieve(doc.storage_path)
    filename = doc.original_filename or doc.doc_key

    logger.info(
        "Dispense processing: doc_key={doc_key} file={filename} size={size}",
        doc_key=doc.doc_key,
        filename=filename,
        size=len(file_bytes),
    )

    report_data = extract_report_from_file(file_bytes, filename)
    summary = store_report(db, report_data)
    return summary
