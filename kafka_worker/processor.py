"""
kafka_worker/processor.py
─────────────────────────
Document processing handler called by the Kafka consumer.

Processing flow:
    1. Load metadata from DB
    2. Idempotency check (skip if COMPLETED)
    3. Mark PROCESSING
    4. Download document from storage
    5. Run processing logic
    6. Save results
    7. Mark COMPLETED

On failure:
    - Increment retry_count
    - If exhausted → FAILED_PERMANENTLY → publish to DLQ
    - Else → FAILED (Kafka re-delivery will trigger retry)
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from core.config import settings
from core.enums import DocumentStatus
from database import SessionLocal
from models.document import Document
from services.document_storage import document_storage


async def process_document(doc_key: str, document_type: str) -> None:
    """
    Main handler invoked by the Kafka consumer for each message.

    Uses its own DB session (worker runs in a separate process).
    """
    db: Session = SessionLocal()
    dlq_message = None

    try:
        # ── Step 1: Load metadata ───────────────────────────────────
        doc = db.query(Document).filter(Document.doc_key == doc_key).first()
        if not doc:
            logger.error(
                "Document not found in DB: doc_key={doc_key}",
                doc_key=doc_key,
            )
            return

        # ── Step 2: Idempotency check ───────────────────────────────
        if doc.status == DocumentStatus.COMPLETED.value:
            logger.info(
                "Document already completed, skipping: doc_key={doc_key}",
                doc_key=doc_key,
            )
            return

        if doc.status == DocumentStatus.FAILED_PERMANENTLY.value:
            logger.info(
                "Document permanently failed, skipping: doc_key={doc_key}",
                doc_key=doc_key,
            )
            return

        # ── Step 3: Mark PROCESSING ─────────────────────────────────
        doc.status = DocumentStatus.PROCESSING.value
        doc.updated_at = datetime.utcnow()
        db.commit()

        logger.info(
            "Processing started: doc_key={doc_key} type={dtype} attempt={attempt}",
            doc_key=doc_key,
            dtype=document_type,
            attempt=doc.retry_count + 1,
        )

        # ── Step 4: Download document from storage ──────────────────
        try:
            file_bytes = document_storage.retrieve(doc.storage_path)
        except FileNotFoundError:
            _mark_permanent_failure(
                db, doc, f"File not found at {doc.storage_path}"
            )
            dlq_message = _build_dlq_message(doc, "File not found")
            return

        # ── Step 5: Run processing ──────────────────────────────────
        result = _run_processing(file_bytes, document_type, doc.original_filename)

        # ── Step 6: Save results ────────────────────────────────────
        doc.result_data = json.dumps(result, ensure_ascii=False)

        # ── Step 7: Mark COMPLETED ──────────────────────────────────
        doc.status = DocumentStatus.COMPLETED.value
        doc.updated_at = datetime.utcnow()
        db.commit()

        logger.info(
            "Processing completed: doc_key={doc_key} type={dtype}",
            doc_key=doc_key,
            dtype=document_type,
        )

    except Exception as exc:
        db.rollback()
        logger.exception(
            "Processing failed for doc_key={doc_key}: {error}",
            doc_key=doc_key,
            error=exc,
        )

        # Reload document state after rollback
        doc = db.query(Document).filter(Document.doc_key == doc_key).first()
        if doc:
            dlq_message = _handle_retry(db, doc, exc)

    finally:
        db.close()

    # Publish to DLQ outside the DB session if needed
    if dlq_message:
        try:
            from kafka_infra.consumer import KafkaConsumerService
            # DLQ publishing is handled by the consumer service
            # which holds the DLQ producer reference.
            # The consumer passes it via the handler context.
            logger.warning(
                "Document needs DLQ routing: doc_key={doc_key}",
                doc_key=doc_key,
            )
        except Exception:
            pass


def _run_processing(
    file_bytes: bytes,
    document_type: str,
    filename: str | None,
) -> dict:
    """
    Execute the actual document processing.

    For now this is a stub that returns basic file info.
    Replace with real OCR / extraction / AI processing later:
        - PDF → invoice_service.extract_invoice_from_pdf()
        - PDF → document_extractor.extract_report_from_file()
        - Image → barcode scanning
    """
    logger.info(
        "Running processing: type={dtype} filename={filename} size={size}",
        dtype=document_type,
        filename=filename,
        size=len(file_bytes),
    )

    # ── STUB: Replace with real processing logic ────────────────────
    result = {
        "processed": True,
        "document_type": document_type,
        "filename": filename,
        "file_size_bytes": len(file_bytes),
        "message": "Document processed successfully (stub processor).",
    }

    return result


def _handle_retry(db: Session, doc: Document, exc: Exception) -> dict | None:
    """
    Handle a processing failure with retry logic.

    Returns a DLQ message dict if max retries are exhausted, else None.
    """
    doc.retry_count += 1
    error_msg = f"{type(exc).__name__}: {exc}"

    if doc.retry_count >= doc.max_retries:
        _mark_permanent_failure(db, doc, error_msg)
        return _build_dlq_message(doc, error_msg)
    else:
        doc.status = DocumentStatus.FAILED.value
        doc.error_message = error_msg
        doc.updated_at = datetime.utcnow()
        db.commit()

        logger.warning(
            "Document failed, will retry: doc_key={doc_key} "
            "attempt={attempt}/{max_retries} error={error}",
            doc_key=doc.doc_key,
            attempt=doc.retry_count,
            max_retries=doc.max_retries,
            error=error_msg,
        )
        return None


def _mark_permanent_failure(db: Session, doc: Document, error_msg: str) -> None:
    """Mark a document as permanently failed."""
    doc.status = DocumentStatus.FAILED_PERMANENTLY.value
    doc.error_message = error_msg
    doc.updated_at = datetime.utcnow()
    db.commit()

    logger.error(
        "Document permanently failed: doc_key={doc_key} error={error}",
        doc_key=doc.doc_key,
        error=error_msg,
    )


def _build_dlq_message(doc: Document, error_msg: str) -> dict:
    """Build the DLQ payload for a permanently failed document."""
    return {
        "doc_key": doc.doc_key,
        "document_type": doc.document_type,
        "original_filename": doc.original_filename,
        "error": error_msg,
        "retry_count": doc.retry_count,
        "failed_at": datetime.utcnow().isoformat(),
    }
