"""
routes/documents.py
───────────────────
Unified async document processing endpoint.

Flow (async-await UX — the caller waits for the result):
    1. Validate file against the requested process_type
    2. Store file to local storage
    3. Create DB record (QUEUED)
    4. Register an in-memory Future for this doc_key (result bus)
    5. Publish a job to the <process_type>-processing topic
    6. Await the worker's result (push, not poll) up to a timeout
       → return the processed data inline
    7. On timeout, return 202 + doc_key (poll GET /documents/{doc_key})

Processing itself happens in the per-type kafka_worker processes.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.config import settings
from core.enums import ALLOWED_EXTENSIONS, DocumentStatus, ProcessType
from database import get_db
from kafka_infra.messages import ProcessingJob
from kafka_infra.producer import kafka_producer
from kafka_infra.result_bus import result_bus
from models.document import Document
from schemas.document_schemas import (
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from services.document_storage import document_storage

router = APIRouter(prefix="/documents", tags=["Document Processing"])


def _get_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


# ── POST /documents/process ──────────────────────────────────────────────────


@router.post(
    "/process",
    response_model=DocumentUploadResponse,
    summary="Upload a document and await its processed result",
    description=(
        "Upload a single document together with a `process_type` "
        "(`dispense`, `invoice`, or `barcode`). The file is stored, a job is "
        "published to that type's Kafka topic, and the request waits for the "
        "worker to finish — returning the processed data inline.\n\n"
        "**Allowed files per type**\n"
        "- `dispense` → .pdf .docx .doc .xlsx .xls\n"
        "- `invoice`  → .pdf\n"
        "- `barcode`  → .png .jpg .jpeg\n\n"
        "If processing exceeds the server timeout, the response is `202`-style "
        "(`status=QUEUED`) with a `doc_key` you can poll via `GET /documents/{doc_key}`."
    ),
)
async def process_document(
    process_type: ProcessType = Form(..., description="dispense | invoice | barcode"),
    file: UploadFile = File(..., description="Document file to process"),
    db: Session = Depends(get_db),
):
    # ── Validate file type for this process type ────────────────────
    filename = file.filename or "unknown"
    extension = _get_extension(filename)
    allowed = ALLOWED_EXTENSIONS[process_type]
    if extension not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file '.{extension}' for process_type "
                f"'{process_type.value}'. Allowed: "
                f"{', '.join(f'.{e}' for e in sorted(allowed))}"
            ),
        )

    # ── Read + size check ───────────────────────────────────────────
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    max_bytes = settings.DOCUMENT_MAX_FILE_SIZE_MB * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File size ({len(file_bytes) / 1024 / 1024:.1f} MB) exceeds "
                f"maximum allowed ({settings.DOCUMENT_MAX_FILE_SIZE_MB} MB)."
            ),
        )

    doc_key = uuid.uuid4().hex

    # ── Store file ──────────────────────────────────────────────────
    try:
        storage_path = document_storage.store(file_bytes, doc_key, extension)
    except Exception as exc:
        logger.exception("Failed to store document: {error}", error=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store document.",
        )

    # ── Create DB record (QUEUED) ───────────────────────────────────
    db_doc = Document(
        doc_key=doc_key,
        document_type=extension,
        process_type=process_type.value,
        original_filename=filename,
        storage_path=storage_path,
        file_size=len(file_bytes),
        status=DocumentStatus.QUEUED.value,
        max_retries=settings.DOCUMENT_MAX_RETRIES,
    )
    db.add(db_doc)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        document_storage.delete(storage_path)
        logger.exception("Failed to create document record: {error}", error=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create document record.",
        )

    # ── Register interest BEFORE publishing (avoid result race) ──────
    future = result_bus.register(doc_key)

    # ── Publish job ─────────────────────────────────────────────────
    try:
        await kafka_producer.publish_job(
            ProcessingJob.create(doc_key=doc_key, process_type=process_type.value)
        )
    except Exception as exc:
        result_bus.unregister(doc_key)
        logger.error(
            "Kafka publish failed for doc_key={dk}: {err}", dk=doc_key, err=exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processing queue unavailable. Please retry.",
        )

    logger.info(
        "Document queued: doc_key={dk} type={type} file={file}",
        dk=doc_key,
        type=process_type.value,
        file=filename,
    )

    # ── Await the worker's result (push-based) ──────────────────────
    try:
        result = await asyncio.wait_for(
            future, timeout=settings.PROCESSING_RESULT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        result_bus.unregister(doc_key)
        return DocumentUploadResponse(
            doc_key=doc_key,
            process_type=process_type.value,
            status=DocumentStatus.QUEUED.value,
            message=(
                "Still processing. Poll GET /documents/{doc_key} for the result."
            ),
        )
    except asyncio.CancelledError:
        result_bus.unregister(doc_key)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server shutting down; processing will continue in background.",
        )

    if result.status == DocumentStatus.COMPLETED.value:
        return DocumentUploadResponse(
            doc_key=doc_key,
            process_type=process_type.value,
            status=result.status,
            message="Document processed successfully.",
            data=result.result_data,
        )

    # Permanent failure (exhausted retries → DLQ)
    return DocumentUploadResponse(
        doc_key=doc_key,
        process_type=process_type.value,
        status=result.status,
        message="Document processing failed after all retries.",
        error=result.error,
    )


# ── GET /documents/{doc_key} ────────────────────────────────────────────────


@router.get(
    "/{doc_key}",
    response_model=DocumentStatusResponse,
    summary="Check document processing status",
)
def get_document_status(doc_key: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.doc_key == doc_key).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_key}' not found.",
        )
    return doc


# ── GET /documents/ ─────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=DocumentListResponse,
    summary="List all documents",
)
def list_documents(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    total = db.query(func.count(Document.id)).scalar() or 0
    docs = (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return DocumentListResponse(documents=docs, total=total)
