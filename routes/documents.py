"""
routes/documents.py
───────────────────
Extraction-only upload endpoint.

The Kafka handler runs the OCR / LLM / barcode extraction and stashes
the parsed JSON on `Document.result_data`. NO `invoices` / `drug_reports`
/ inventory rows are written here — that's `POST /invoices` and
`POST /dispenses`.

Per-process_type file count limits:
    invoice   → exactly 1 PDF
    dispense  → exactly 1 PDF/DOCX/DOC/XLSX/XLS
    barcode   → 1 or 2 image files (one of the two may carry only the
                barcode or only the datamatrix — the pairing service
                merges them)
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.config import settings
from core.enums import ALLOWED_EXTENSIONS, DocumentStatus, ProcessType
from kafka_infra.messages import ProcessingJob
from kafka_infra.producer import kafka_producer
from kafka_infra.result_bus import result_bus
from middlewares.auth import auth_incoming_req
from models.document import Document
from schemas.document_schemas import (
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.activity_service import log_activity
from services.document_storage import document_storage
from services.pharmacy_authz import ensure_pharmacy_access

router = APIRouter(prefix="/documents", tags=["Document Processing"])


_SINGLE_FILE_TYPES = {ProcessType.INVOICE, ProcessType.DISPENSE}


def _get_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _validate_count(process_type: ProcessType, files: list[UploadFile]) -> None:
    if process_type in _SINGLE_FILE_TYPES:
        if len(files) != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"process_type='{process_type.value}' accepts exactly 1 file "
                    f"(got {len(files)})."
                ),
            )
        return

    # barcode
    if not (1 <= len(files) <= 2):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"process_type='barcode' accepts 1 or 2 image files (got {len(files)})."),
        )


async def _read_and_validate_file(
    file: UploadFile, process_type: ProcessType
) -> tuple[bytes, str, str]:
    """Return (bytes, filename, extension) after extension + size checks."""
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

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File '{filename}' is empty.",
        )
    max_bytes = settings.DOCUMENT_MAX_FILE_SIZE_MB * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File '{filename}' ({len(file_bytes) / 1024 / 1024:.1f} MB) "
                f"exceeds max ({settings.DOCUMENT_MAX_FILE_SIZE_MB} MB)."
            ),
        )
    return file_bytes, filename, extension


# ── POST /documents/process ─────────────────────────────────────────────────


@router.post(
    "/process",
    response_model=DocumentUploadResponse,
    summary="Upload a document for extraction (no DB write of domain rows)",
    description=(
        "Upload a file (or 2 images for `barcode`) tied to a "
        "`medical_store_id`. The worker extracts structured JSON and returns "
        "it inline — no `invoices` / `drug_reports` rows are created. To "
        "persist, the client POSTs the (possibly edited) JSON to "
        "`/invoices` or `/dispenses`.\n\n"
        "**File-count limits per process_type**\n"
        "- `invoice`  → 1 PDF\n"
        "- `dispense` → 1 PDF/DOCX/DOC/XLSX/XLS\n"
        "- `barcode`  → 1 or 2 images (.png .jpg .jpeg)"
    ),
)
async def process_document(
    process_type: ProcessType = Form(..., description="dispense | invoice | barcode"),
    medical_store_id: int = Form(..., description="Medical store the doc belongs to"),
    files: list[UploadFile] = File(..., description="1 file (2 images for barcode)"),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, medical_store_id)
    _validate_count(process_type, files)

    # Validate + read every file BEFORE we create any Document row, so a
    # malformed second image doesn't leave a half-written first one.
    parsed: list[tuple[bytes, str, str]] = []
    for f in files:
        parsed.append(await _read_and_validate_file(f, process_type))

    doc_key = uuid.uuid4().hex

    # Store the first file at the Document's storage_path.
    primary_bytes, primary_name, primary_ext = parsed[0]
    try:
        primary_path = document_storage.store(primary_bytes, doc_key, primary_ext)
    except Exception as exc:
        logger.exception("Failed to store document: {error}", error=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store document.",
        ) from exc

    progress: dict | None = None
    if len(parsed) == 2:
        second_bytes, second_name, second_ext = parsed[1]
        try:
            second_path = document_storage.store(second_bytes, f"{doc_key}-2", second_ext)
        except Exception as exc:
            document_storage.delete(primary_path)
            logger.exception("Failed to store second image: {error}", error=exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to store second image.",
            ) from exc
        progress = {
            "second_image_path": second_path,
            "second_original_filename": second_name,
        }

    db_doc = Document(
        doc_key=doc_key,
        medical_store_id=medical_store_id,
        uploaded_by_user_id=user.user_id,
        document_type=primary_ext,
        process_type=process_type.value,
        original_filename=primary_name,
        storage_path=primary_path,
        file_size=len(primary_bytes),
        status=DocumentStatus.QUEUED.value,
        max_retries=settings.DOCUMENT_MAX_RETRIES,
        progress=progress,
    )
    db.add(db_doc)
    await db.flush()
    await log_activity(
        db,
        medical_store_id=medical_store_id,
        actor=user,
        action="DOCUMENT_UPLOADED",
        entity_type="document",
        entity_id=db_doc.id,
        summary=f"Uploaded {process_type.value} document '{primary_name}'",
        meta={
            "doc_key": doc_key,
            "process_type": process_type.value,
            "original_filename": primary_name,
            "file_count": len(parsed),
        },
    )
    try:
        await db.commit()
        await db.refresh(db_doc)
    except Exception as exc:
        await db.rollback()
        document_storage.delete(primary_path)
        if progress and progress.get("second_image_path"):
            document_storage.delete(progress["second_image_path"])
        logger.exception("Failed to create document record: {error}", error=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create document record.",
        ) from exc

    future = result_bus.register(doc_key)

    try:
        await kafka_producer.publish_job(
            ProcessingJob.create(
                doc_key=doc_key,
                process_type=process_type.value,
                medical_store_id=medical_store_id,
            )
        )
    except Exception as exc:
        result_bus.unregister(doc_key)
        logger.error("Kafka publish failed for doc_key={dk}: {err}", dk=doc_key, err=exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processing queue unavailable. Please retry.",
        ) from exc

    logger.info(
        "Document queued: doc_key={dk} type={t} ms_id={ph} files={n}",
        dk=doc_key,
        t=process_type.value,
        ph=medical_store_id,
        n=len(files),
    )

    try:
        result = await asyncio.wait_for(future, timeout=settings.PROCESSING_RESULT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        result_bus.unregister(doc_key)
        return DocumentUploadResponse(
            doc_key=doc_key,
            process_type=process_type.value,
            status=DocumentStatus.QUEUED.value,
            message=("Still processing. Poll GET /documents/{doc_key} for the result."),
        )
    except asyncio.CancelledError as exc:
        result_bus.unregister(doc_key)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server shutting down; processing will continue in background.",
        ) from exc

    if result.status == DocumentStatus.COMPLETED.value:
        return DocumentUploadResponse(
            doc_key=doc_key,
            process_type=process_type.value,
            status=result.status,
            message="Document processed successfully.",
            data=result.result_data,
        )

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
async def get_document_status(
    doc_key: str,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    result = await db.execute(select(Document).where(Document.doc_key == doc_key))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_key}' not found.",
        )
    await ensure_pharmacy_access(db, user, doc.medical_store_id)
    return doc


# ── GET /documents/ ─────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=DocumentListResponse,
    summary="List documents (pharmacy-scoped for non-admin)",
)
async def list_documents(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    base = select(Document).order_by(Document.created_at.desc())
    count_stmt = select(func.count(Document.id))

    if user.role.value != "ADMIN":
        from models.pharmacy import Pharmacy

        if user.role.value == "PHARMACY_OWNER":
            owner_ids_stmt = select(Pharmacy.medical_store_id).where(
                Pharmacy.user_id == user.user_id
            )
            owner_ids = (await db.execute(owner_ids_stmt)).scalars().all()
            base = base.where(Document.medical_store_id.in_(owner_ids))
            count_stmt = count_stmt.where(Document.medical_store_id.in_(owner_ids))
        else:  # TECHNICIAN
            base = base.where(Document.medical_store_id == user.medical_store_id)
            count_stmt = count_stmt.where(Document.medical_store_id == user.medical_store_id)

    total = (await db.execute(count_stmt)).scalar() or 0
    docs = (await db.execute(base.offset(skip).limit(limit))).scalars().all()
    return DocumentListResponse(documents=docs, total=total)
