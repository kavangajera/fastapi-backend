"""
kafka_infra/consumer.py
───────────────────────
Kafka consumer for the worker process.

This runs in a SEPARATE process from FastAPI.
Start it with: python -m kafka_worker.main

Key design:
    - Manual offset commit (only after successful processing)
    - If worker crashes → offset not committed → Kafka re-delivers
    - Consumer group enables horizontal scaling
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from loguru import logger

from core.config import settings


# Type for the handler function signature
HandlerFn = Callable[[str, str], Awaitable[None]]


class KafkaConsumerService:
    """
    Kafka consumer that pulls document processing jobs and delegates
    to a handler function.
    """

    def __init__(self) -> None:
        self._consumer: AIOKafkaConsumer | None = None
        self._dlq_producer: AIOKafkaProducer | None = None
        self._running: bool = False

    async def start(self) -> None:
        """Connect to Kafka broker and join the consumer group."""
        self._consumer = AIOKafkaConsumer(
            settings.KAFKA_DOCUMENT_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=settings.KAFKA_CONSUMER_GROUP,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            key_deserializer=lambda k: k.decode("utf-8") if k else None,
            enable_auto_commit=False,           # manual commit only
            auto_offset_reset="earliest",       # don't miss messages
            max_poll_interval_ms=600_000,       # 10 min for heavy processing
            session_timeout_ms=30_000,
        )
        await self._consumer.start()
        logger.info(
            "Kafka consumer started: broker={broker} group={group} topic={topic}",
            broker=settings.KAFKA_BOOTSTRAP_SERVERS,
            group=settings.KAFKA_CONSUMER_GROUP,
            topic=settings.KAFKA_DOCUMENT_TOPIC,
        )

        # DLQ producer for permanently failed messages
        self._dlq_producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await self._dlq_producer.start()
        logger.info("DLQ producer started: topic={topic}", topic=settings.KAFKA_DLQ_TOPIC)

    async def stop(self) -> None:
        """Gracefully stop consumer and DLQ producer."""
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("Kafka consumer stopped")
            self._consumer = None
        if self._dlq_producer:
            await self._dlq_producer.stop()
            logger.info("DLQ producer stopped")
            self._dlq_producer = None

    async def publish_to_dlq(self, message: dict) -> None:
        """Send a permanently failed message to the Dead Letter Queue."""
        if not self._dlq_producer:
            logger.error("DLQ producer not available, cannot publish to DLQ")
            return
        await self._dlq_producer.send_and_wait(
            topic=settings.KAFKA_DLQ_TOPIC,
            key=message.get("doc_key"),
            value=message,
        )
        logger.warning(
            "Message sent to DLQ: doc_key={doc_key}",
            doc_key=message.get("doc_key"),
        )

    async def consume_forever(self, handler: HandlerFn) -> None:
        """
        Main consumption loop.

        For each message:
            1. Deserialize payload
            2. Call handler(doc_key, document_type)
            3. Commit offset ONLY on success
            4. On failure, the handler is responsible for retry logic
               and DLQ routing
        """
        if not self._consumer:
            raise RuntimeError(
                "Consumer not started. Call consumer.start() first."
            )

        self._running = True
        logger.info("Consumer loop started — waiting for messages...")

        try:
            async for msg in self._consumer:
                if not self._running:
                    break

                payload = msg.value
                doc_key = payload.get("doc_key")
                document_type = payload.get("document_type")

                logger.info(
                    "Received message: doc_key={doc_key} type={dtype} "
                    "partition={partition} offset={offset}",
                    doc_key=doc_key,
                    dtype=document_type,
                    partition=msg.partition,
                    offset=msg.offset,
                )

                try:
                    await handler(doc_key, document_type)

                    # Commit offset ONLY after successful processing
                    await self._consumer.commit()
                    logger.info(
                        "Offset committed: doc_key={doc_key} partition={partition} offset={offset}",
                        doc_key=doc_key,
                        partition=msg.partition,
                        offset=msg.offset,
                    )
                except Exception as exc:
                    logger.exception(
                        "Handler failed for doc_key={doc_key}: {error}",
                        doc_key=doc_key,
                        error=exc,
                    )
                    # Commit anyway to avoid infinite re-processing loop.
                    # The handler itself is responsible for updating
                    # retry_count and status in the DB, and publishing
                    # to DLQ when max retries are exhausted.
                    await self._consumer.commit()
        finally:
            logger.info("Consumer loop exited")
