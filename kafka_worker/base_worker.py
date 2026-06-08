"""
kafka_worker/base_worker.py
───────────────────────────
Generic, reusable Kafka worker for ONE process type.

Guarantees:
    • enable_auto_commit = False  (manual commit only)
    • offset is committed ONLY after the outcome is durably handed off
      (result published, OR retry scheduled, OR DLQ written)
    • non-blocking retries via the <type>-retry topic with backoff
    • terminal failures land in <type>-dlq AND notify the API via results

Per-message flow:
    parse job → load Document → mark PROCESSING
      → run handler (in a thread)
          success → COMPLETED + publish_result + commit
          failure → attempt < max ? schedule retry : DLQ + FAILED result
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta

from aiokafka import AIOKafkaConsumer
from loguru import logger
from sqlalchemy.orm import Session

from core.config import settings
from core.enums import DocumentStatus, ProcessType
from database import SessionLocal
from kafka_infra import topics
from kafka_infra.messages import ProcessingJob, ProcessingResult
from kafka_infra.producer import kafka_producer
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
            enable_auto_commit=False,        # manual commit only
            auto_offset_reset="earliest",
            max_poll_interval_ms=600_000,    # 10 min for heavy processing
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

        db: Session = SessionLocal()
        try:
            doc = db.query(Document).filter(Document.doc_key == job.doc_key).first()
            if not doc:
                logger.error("Document not found, skipping: doc_key={dk}", dk=job.doc_key)
                return

            # Idempotency: don't reprocess terminal documents.
            if doc.status in (
                DocumentStatus.COMPLETED.value,
                DocumentStatus.FAILED_PERMANENTLY.value,
            ):
                logger.info(
                    "Document already terminal ({status}), skipping: doc_key={dk}",
                    status=doc.status,
                    dk=job.doc_key,
                )
                return

            # Mark PROCESSING (retry_count is 0-based: attempt 1 → 0 prior retries)
            doc.status = DocumentStatus.PROCESSING.value
            doc.retry_count = job.attempt - 1
            doc.updated_at = datetime.utcnow()
            db.commit()

            logger.info(
                "Processing: doc_key={dk} type={type} attempt={attempt}/{max}",
                dk=job.doc_key,
                type=self.process_type.value,
                attempt=job.attempt,
                max=settings.DOCUMENT_MAX_RETRIES,
            )

            # Run the (blocking) handler off the event loop.
            result_data = await asyncio.to_thread(self.handler, db, doc)

            doc.status = DocumentStatus.COMPLETED.value
            doc.result_data = json.dumps(result_data, ensure_ascii=False, default=str)
            doc.error_message = None
            doc.updated_at = datetime.utcnow()
            db.commit()

            await kafka_producer.publish_result(
                ProcessingResult(
                    doc_key=job.doc_key,
                    process_type=self.process_type.value,
                    status=DocumentStatus.COMPLETED.value,
                    result_data=result_data,
                    retry_count=doc.retry_count,
                )
            )
            logger.info("Completed: doc_key={dk}", dk=job.doc_key)

        except Exception as exc:
            db.rollback()
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception(
                "Handler failed: doc_key={dk} attempt={attempt} error={err}",
                dk=job.doc_key,
                attempt=job.attempt,
                err=error_msg,
            )
            await self._handle_failure(db, job, error_msg)
        finally:
            db.close()

    async def _handle_failure(self, db: Session, job: ProcessingJob, error_msg: str) -> None:
        """Schedule a delayed retry, or route to DLQ when attempts are exhausted."""
        doc = db.query(Document).filter(Document.doc_key == job.doc_key).first()

        if job.attempt < settings.DOCUMENT_MAX_RETRIES:
            # ── Schedule a non-blocking retry ────────────────────────
            delay = settings.KAFKA_RETRY_BACKOFF_BASE_SECONDS * (2 ** (job.attempt - 1))
            process_after = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()

            if doc:
                doc.status = DocumentStatus.FAILED.value
                doc.retry_count = job.attempt
                doc.error_message = error_msg
                doc.updated_at = datetime.utcnow()
                db.commit()

            await kafka_producer.publish_retry(
                ProcessingJob(
                    doc_key=job.doc_key,
                    process_type=job.process_type,
                    attempt=job.attempt + 1,
                    process_after=process_after,
                )
            )
            logger.warning(
                "Retry scheduled: doc_key={dk} next_attempt={na} delay={delay}s",
                dk=job.doc_key,
                na=job.attempt + 1,
                delay=delay,
            )
        else:
            # ── Exhausted → DLQ + FAILED result ──────────────────────
            if doc:
                doc.status = DocumentStatus.FAILED_PERMANENTLY.value
                doc.retry_count = job.attempt
                doc.error_message = error_msg
                doc.updated_at = datetime.utcnow()
                db.commit()

            await kafka_producer.publish_dlq(job, error_msg)
            await kafka_producer.publish_result(
                ProcessingResult(
                    doc_key=job.doc_key,
                    process_type=self.process_type.value,
                    status=DocumentStatus.FAILED_PERMANENTLY.value,
                    error=error_msg,
                    retry_count=job.attempt,
                )
            )
            logger.error("Permanently failed → DLQ: doc_key={dk}", dk=job.doc_key)
