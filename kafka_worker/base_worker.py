"""
kafka_worker/base_worker.py
───────────────────────────
Generic async Kafka worker for ONE process type.

Guarantees:
    • enable_auto_commit = False  (manual commit only)
    • offset committed ONLY after the outcome is durably handed off
      (result published, OR retry scheduled, OR DLQ written)
    • non-blocking retries via the <type>-retry topic with backoff
    • terminal failures land in <type>-dlq AND notify the API via results
    • resume-from-progress: handlers read `doc.processed_items_count` /
      `doc.progress` and skip already-saved items

Per-message flow:
    parse job → load Document → mark PROCESSING
      → run async handler
          success → COMPLETED + publish_result + commit
          failure → attempt < max ? schedule retry : DLQ + FAILED result
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from aiokafka import AIOKafkaConsumer
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import AsyncSessionLocal
from core.config import settings
from core.enums import DocumentStatus, ProcessType
from kafka_infra import topics
from kafka_infra.messages import ProcessingJob, ProcessingResult
from kafka_infra.producer import kafka_producer
from kafka_worker.errors import PermanentDocumentError
from kafka_worker.handlers import get_handler
from models.document import Document


class Worker:
    """Main consumer for a single process type's ``<type>-processing`` topic."""

    def __init__(self, process_type: ProcessType) -> None:
        self.process_type = process_type
        self.topic = topics.main_topic(process_type)
        self.group = topics.worker_group(process_type)
        self.handler = get_handler(process_type)
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=self.group,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            key_deserializer=lambda k: k.decode("utf-8") if k else None,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            max_poll_interval_ms=600_000,
            session_timeout_ms=30_000,
        )
        await self._consumer.start()
        logger.info(
            "Worker started: type={type} topic={topic} group={group}",
            type=self.process_type.value,
            topic=self.topic,
            group=self.group,
        )

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None
            logger.info("Worker stopped: type={type}", type=self.process_type.value)

    async def run(self) -> None:
        if not self._consumer:
            raise RuntimeError("Worker not started. Call start() first.")
        self._running = True
        logger.info("Worker loop running: type={type}", type=self.process_type.value)
        try:
            async for msg in self._consumer:
                if not self._running:
                    break
                await self._process_one(msg.value)
                await self._consumer.commit()
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("Worker loop exited: type={type}", type=self.process_type.value)

    # ── Single-message processing ────────────────────────────────────

    async def _process_one(self, raw: dict) -> None:
        try:
            job = ProcessingJob(**raw)
        except Exception as exc:
            logger.error("Malformed job skipped: {raw} ({error})", raw=raw, error=exc)
            return

        async with AsyncSessionLocal() as session:
            doc_result = await session.execute(
                select(Document).where(Document.doc_key == job.doc_key)
            )
            doc = doc_result.scalar_one_or_none()
            if not doc:
                logger.error("Document not found: doc_key={dk}", dk=job.doc_key)
                return

            if doc.status in (
                DocumentStatus.COMPLETED.value,
                DocumentStatus.FAILED_PERMANENTLY.value,
            ):
                logger.info(
                    "Document already terminal ({s}), skipping: doc_key={dk}",
                    s=doc.status,
                    dk=job.doc_key,
                )
                return

            doc.status = DocumentStatus.PROCESSING.value
            doc.retry_count = job.attempt - 1
            doc.updated_at = datetime.utcnow()
            await session.commit()

            logger.info(
                "Processing: doc_key={dk} type={t} attempt={a}/{m} ms_id={ph}",
                dk=job.doc_key,
                t=self.process_type.value,
                a=job.attempt,
                m=settings.DOCUMENT_MAX_RETRIES,
                ph=job.medical_store_id,
            )

            try:
                result_data = await self.handler(
                    session,
                    doc,
                    medical_store_id=job.medical_store_id,
                )
                doc.status = DocumentStatus.COMPLETED.value
                doc.result_data = json.dumps(result_data, ensure_ascii=False, default=str)
                doc.error_message = None
                doc.updated_at = datetime.utcnow()
                await session.commit()

                await kafka_producer.publish_result(
                    ProcessingResult(
                        doc_key=job.doc_key,
                        process_type=self.process_type.value,
                        medical_store_id=job.medical_store_id,
                        status=DocumentStatus.COMPLETED.value,
                        result_data=result_data,
                        retry_count=doc.retry_count,
                    )
                )
                logger.info("Completed: doc_key={dk}", dk=job.doc_key)
            except PermanentDocumentError as exc:
                await session.rollback()
                error_msg = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Non-retryable document failure: doc_key={dk} error={err}",
                    dk=job.doc_key,
                    err=error_msg,
                )
                await self._handle_failure(
                    session,
                    job,
                    error_msg,
                    permanent=True,
                    error_code=exc.status_code,
                )
            except Exception as exc:
                await session.rollback()
                error_msg = f"{type(exc).__name__}: {exc}"
                logger.exception(
                    "Handler failed: doc_key={dk} attempt={a} error={err}",
                    dk=job.doc_key,
                    a=job.attempt,
                    err=error_msg,
                )
                await self._handle_failure(session, job, error_msg)

    async def _handle_failure(
        self,
        session: AsyncSession,
        job: ProcessingJob,
        error_msg: str,
        *,
        permanent: bool = False,
        error_code: int | None = None,
    ) -> None:
        result = await session.execute(select(Document).where(Document.doc_key == job.doc_key))
        doc = result.scalar_one_or_none()

        if not permanent and job.attempt < settings.DOCUMENT_MAX_RETRIES:
            delay = settings.KAFKA_RETRY_BACKOFF_BASE_SECONDS * (2 ** (job.attempt - 1))
            process_after = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()

            if doc:
                doc.status = DocumentStatus.FAILED.value
                doc.retry_count = job.attempt
                doc.error_message = error_msg
                doc.updated_at = datetime.utcnow()
                await session.commit()

            await kafka_producer.publish_retry(
                ProcessingJob(
                    doc_key=job.doc_key,
                    process_type=job.process_type,
                    medical_store_id=job.medical_store_id,
                    attempt=job.attempt + 1,
                    process_after=process_after,
                )
            )
            logger.warning(
                "Retry scheduled: doc_key={dk} next_attempt={na} delay={d}s",
                dk=job.doc_key,
                na=job.attempt + 1,
                d=delay,
            )
        else:
            if doc:
                doc.status = DocumentStatus.FAILED_PERMANENTLY.value
                doc.retry_count = job.attempt
                doc.error_message = error_msg
                doc.updated_at = datetime.utcnow()
                await session.commit()

            await kafka_producer.publish_dlq(job, error_msg)
            await kafka_producer.publish_result(
                ProcessingResult(
                    doc_key=job.doc_key,
                    process_type=self.process_type.value,
                    medical_store_id=job.medical_store_id,
                    status=DocumentStatus.FAILED_PERMANENTLY.value,
                    error=error_msg,
                    error_code=error_code,
                    retry_count=job.attempt,
                )
            )
            logger.error("Permanently failed → DLQ: doc_key={dk}", dk=job.doc_key)
