"""
routes/documents.py
───────────────────
FastAPI router for document upload and status tracking.

This is the API + Producer layer:
    1. Accept document upload
    2. Store file to local storage
    3. Create DB record (QUEUED)
    4. Publish job to Kafka
    5. Return immediately

Processing happens in the kafka_worker process, NOT here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.config import settings
from core.enums import DocumentStatus, DocumentType
from database import get_db
from kafka_infra.producer import kafka_producer
from models.document import Document
from schemas.document_schemas import (
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from services.document_storage import document_storage

router = APIRouter(prefix="/documents", tags=["Document Processing"])

# Allowed extensions → DocumentType mapping
_EXTENSION_MAP: dict[str, DocumentType] = {
    "pdf": DocumentType.PDF,
    "png": DocumentType.IMAGE,
    "jpg": DocumentType.IMAGE,
    "jpeg": DocumentType.IMAGE,
    "csv": DocumentType.CSV,
}


def _get_extension(filename: str) -> str:
    """Extract lowercase extension from filename."""
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


# ── POST /documents/ ────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document for async processing",
    description=(
        "Upload a document (PDF, image, or CSV). The file is stored locally, "
        "a processing job is published to Kafka, and the API returns immediately "
        "with a `doc_key` for status polling.\n\n"
        "**Supported formats:** .pdf, .png, .jpg, .jpeg, .csv\n\n"
        "**Max file size:** Configurable via `DOCUMENT_MAX_FILE_SIZE_MB` "
        f"(default: {settings.DOCUMENT_MAX_FILE_SIZE_MB} MB)"
    ),
)
async def upload_document(
    file: UploadFile = File(..., description="Document file to process"),
    db: Session = Depends(get_db),
):
    # ── Validate file type ──────────────────────────────────────────
    filename = file.filename or "unknown"
    extension = _get_extension(filename)
    if extension not in _EXTENSION_MAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type '.{extension}'. "
                f"Allowed: {', '.join(f'.{e}' for e in sorted(_EXTENSION_MAP))}"
            ),
        )
    document_type = _EXTENSION_MAP[extension]

    # ── Read and validate size ──────────────────────────────────────
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

    # ── Step 1: Generate doc_key ────────────────────────────────────
    doc_key = uuid.uuid4().hex

    # ── Step 2: Store file to disk ──────────────────────────────────
    try:
        storage_path = document_storage.store(file_bytes, doc_key, extension)
    except Exception as exc:
        logger.exception("Failed to store document: {error}", error=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store document.",
        )

    # ── Step 3: Create DB record (QUEUED) ───────────────────────────
    db_doc = Document(
        doc_key=doc_key,
        document_type=document_type.value,
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
        # Clean up stored file on DB failure
        document_storage.delete(storage_path)
        logger.exception("Failed to create document record: {error}", error=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create document record.",
        )

    # ── Step 4: Publish job to Kafka ────────────────────────────────
    try:
        await kafka_producer.publish_document_job(
            doc_key=doc_key,
            document_type=document_type.value,
        )
    except Exception as exc:
        # Kafka publish failed — document is stored and in DB as QUEUED.
        # Worker can still pick it up via a recovery sweep later.
        logger.error(
            "Kafka publish failed for doc_key={doc_key}: {error}. "
            "Document is stored and will be retried.",
            doc_key=doc_key,
            error=exc,
        )

    # ── Step 5: Return immediately ──────────────────────────────────
    logger.info(
        "Document queued: doc_key={doc_key} type={dtype} file={filename}",
        doc_key=doc_key,
        dtype=document_type.value,
        filename=filename,
    )

    return DocumentUploadResponse(
        doc_key=doc_key,
        status="queued",
        message="Document accepted for processing.",
    )


# ── GET /documents/{doc_key} ────────────────────────────────────────────────


@router.get(
    "/{doc_key}",
    response_model=DocumentStatusResponse,
    summary="Check document processing status",
    description="Retrieve the current processing status of a document by its `doc_key`.",
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
    description="Paginated list of all documents with their processing status.",
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
