"""Single-document Kafka enqueue and result-wait workflow."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.enums import DocumentStatus, ProcessType
from kafka_infra.messages import ProcessingJob, ProcessingResult
from kafka_infra.producer import kafka_producer
from kafka_infra.result_bus import result_bus
from models.document import Document
from services.document_storage import document_storage


async def enqueue_document(
    db: AsyncSession,
    *,
    file_bytes: bytes,
    filename: str,
    extension: str,
    process_type: ProcessType,
    medical_store_id: int,
    uploaded_by_user_id: int,
    progress: dict | None = None,
) -> tuple[str, ProcessingResult | None]:
    doc_key = uuid.uuid4().hex
    storage_path = document_storage.store(file_bytes, doc_key, extension)
    document = Document(
        doc_key=doc_key,
        medical_store_id=medical_store_id,
        uploaded_by_user_id=uploaded_by_user_id,
        document_type=extension,
        process_type=process_type.value,
        original_filename=filename,
        storage_path=storage_path,
        file_size=len(file_bytes),
        status=DocumentStatus.QUEUED.value,
        max_retries=settings.DOCUMENT_MAX_RETRIES,
        progress=progress,
    )
    db.add(document)
    try:
        await db.commit()
        await db.refresh(document)
    except Exception:
        await db.rollback()
        document_storage.delete(storage_path)
        raise

    future = result_bus.register(doc_key)
    try:
        await kafka_producer.publish_job(
            ProcessingJob.create(doc_key, process_type.value, medical_store_id)
        )
    except Exception:
        result_bus.unregister(doc_key)
        raise

    try:
        result = await asyncio.wait_for(future, timeout=settings.PROCESSING_RESULT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        result_bus.unregister(doc_key)
        return doc_key, None
    except asyncio.CancelledError:
        result_bus.unregister(doc_key)
        raise
    return doc_key, result
