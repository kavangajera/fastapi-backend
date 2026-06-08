"""
kafka_worker/handlers/barcode_handler.py
────────────────────────────────────────
Barcode processing: image → extract NDC, expiration, lot, serial,
GTIN + FDA product lookup. Returns the extracted data (no DB write).

Reuses:
    services.barcode_scanner.BarcodeScannerService.process_barcode_base64
"""

from __future__ import annotations

import base64

from loguru import logger
from sqlalchemy.orm import Session

from models.document import Document
from services.document_storage import document_storage
from services.barcode_scanner import BarcodeScannerService

# One scanner instance reused across messages in this worker process.
_scanner = BarcodeScannerService()


def handle_barcode(db: Session, doc: Document) -> dict:
    """Scan an uploaded barcode/datamatrix image and return extracted data."""
    file_bytes = document_storage.retrieve(doc.storage_path)
    filename = doc.original_filename or doc.doc_key

    logger.info(
        "Barcode processing: doc_key={doc_key} file={filename} size={size}",
        doc_key=doc.doc_key,
        filename=filename,
        size=len(file_bytes),
    )

    image_base64 = base64.b64encode(file_bytes).decode("utf-8")
    result = _scanner.process_barcode_base64(image_base64)
    return result
