"""
kafka_infra/producer.py
───────────────────────
Async Kafka producer singleton.

Used by BOTH the FastAPI app (to publish jobs + results) and the
workers (to publish retries, DLQ entries, and results). Lifecycle in
the app is managed by FastAPI's lifespan; workers manage their own.

Usage:
    from kafka_infra.producer import kafka_producer
    await kafka_producer.publish_job(job)
    await kafka_producer.publish_result(result)
"""

from __future__ import annotations

import json

from aiokafka import AIOKafkaProducer
from loguru import logger

from core.config import settings
from kafka_infra.messages import ProcessingJob, ProcessingResult
from kafka_infra import topics


class KafkaProducerService:
    """Singleton async Kafka producer for jobs, retries, DLQ, and results."""

    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Connect to the Kafka broker. Call once at app/worker startup."""
        if self._producer is not None:
            return
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        try:
            await self._producer.start()
            logger.info(
                "Kafka producer started: broker={broker}",
                broker=settings.KAFKA_BOOTSTRAP_SERVERS,
            )
        except Exception as exc:
            logger.error("Kafka producer failed to start: {error}", error=exc)
            self._producer = None
            raise

    async def stop(self) -> None:
        """Gracefully flush and close the producer."""
        if self._producer:
            await self._producer.stop()
            logger.info("Kafka producer stopped")
            self._producer = None

    def _require(self) -> AIOKafkaProducer:
        if not self._producer:
            raise RuntimeError(
                "Kafka producer is not started. Call kafka_producer.start() first."
            )
        return self._producer

    # ── Jobs ─────────────────────────────────────────────────────────

    async def publish_job(self, job: ProcessingJob) -> None:
        """Publish a job to the main ``<type>-processing`` topic."""
        topic = topics.main_topic(job.process_type)
        await self._require().send_and_wait(
            topic=topic, key=job.doc_key, value=job.model_dump()
        )
        logger.info(
            "Published job: doc_key={doc_key} type={dtype} attempt={attempt} topic={topic}",
            doc_key=job.doc_key,
            dtype=job.process_type,
            attempt=job.attempt,
            topic=topic,
        )

    async def publish_retry(self, job: ProcessingJob) -> None:
        """Publish a job to the ``<type>-retry`` topic for delayed reprocessing."""
        topic = topics.retry_topic(job.process_type)
        await self._require().send_and_wait(
            topic=topic, key=job.doc_key, value=job.model_dump()
        )
        logger.warning(
            "Scheduled retry: doc_key={doc_key} type={dtype} attempt={attempt} "
            "after={after} topic={topic}",
            doc_key=job.doc_key,
            dtype=job.process_type,
            attempt=job.attempt,
            after=job.process_after,
            topic=topic,
        )

    async def publish_dlq(self, job: ProcessingJob, error: str) -> None:
        """Publish a terminally-failed job to the ``<type>-dlq`` topic."""
        topic = topics.dlq_topic(job.process_type)
        payload = job.model_dump()
        payload["error"] = error
        await self._require().send_and_wait(
            topic=topic, key=job.doc_key, value=payload
        )
        logger.error(
            "Sent to DLQ: doc_key={doc_key} type={dtype} topic={topic} error={error}",
            doc_key=job.doc_key,
            dtype=job.process_type,
            topic=topic,
            error=error,
        )

    # ── Results ──────────────────────────────────────────────────────

    async def publish_result(self, result: ProcessingResult) -> None:
        """Publish a terminal result to the shared results topic."""
        topic = topics.results_topic()
        await self._require().send_and_wait(
            topic=topic, key=result.doc_key, value=result.model_dump()
        )
        logger.info(
            "Published result: doc_key={doc_key} status={status} topic={topic}",
            doc_key=result.doc_key,
            status=result.status,
            topic=topic,
        )


# ── Module-level singleton ──────────────────────────────────────────────────
kafka_producer = KafkaProducerService()
