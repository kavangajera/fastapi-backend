"""
kafka_infra/producer.py
───────────────────────
Async Kafka producer singleton.

Lifecycle is managed by FastAPI's lifespan events:
    startup  → kafka_producer.start()
    shutdown → kafka_producer.stop()

Usage from route handlers:
    from kafka_infra.producer import kafka_producer
    await kafka_producer.publish_document_job(doc_key, document_type)
"""

from __future__ import annotations

import json

from aiokafka import AIOKafkaProducer
from loguru import logger

from core.config import settings
from kafka_infra.schemas import DocumentJobMessage


class KafkaProducerService:
    """Singleton async Kafka producer for publishing document processing jobs."""

    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Connect to the Kafka broker. Call once at app startup."""
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
            logger.error(
                "Kafka producer failed to start: {error}",
                error=exc,
            )
            self._producer = None
            raise

    async def stop(self) -> None:
        """Gracefully flush and close the producer. Call at app shutdown."""
        if self._producer:
            await self._producer.stop()
            logger.info("Kafka producer stopped")
            self._producer = None

    async def publish_document_job(
        self,
        doc_key: str,
        document_type: str,
    ) -> None:
        """
        Publish a document processing job to Kafka.

        The message contains only metadata (doc_key + type).
        The actual file is already stored on disk before this call.
        """
        if not self._producer:
            raise RuntimeError(
                "Kafka producer is not started. "
                "Call kafka_producer.start() first."
            )

        message = DocumentJobMessage.create(
            doc_key=doc_key,
            document_type=document_type,
        )
        payload = message.model_dump()

        await self._producer.send_and_wait(
            topic=settings.KAFKA_DOCUMENT_TOPIC,
            key=doc_key,
            value=payload,
        )
        logger.info(
            "Published document job: doc_key={doc_key} type={dtype} topic={topic}",
            doc_key=doc_key,
            dtype=document_type,
            topic=settings.KAFKA_DOCUMENT_TOPIC,
        )


# ── Module-level singleton ──────────────────────────────────────────────────
kafka_producer = KafkaProducerService()
