"""
kafka_worker/main.py
────────────────────
Standalone entry point for the document processing worker.

Run with:
    python -m kafka_worker.main

This is a SEPARATE process from the FastAPI server.
It connects to:
    - Kafka (as a consumer in the 'pdf-workers' group)
    - PostgreSQL/MySQL (to read/update document status)
    - Local storage (to download files for processing)

Scale horizontally by running multiple instances.
Each instance joins the same consumer group, and Kafka
automatically distributes partitions across them.
"""

from __future__ import annotations

import asyncio
import signal
import sys

from loguru import logger

from core.config import settings
from core.logging import setup_logging
from kafka_infra.consumer import KafkaConsumerService
from kafka_worker.processor import process_document


async def main() -> None:
    """Start the Kafka consumer and process documents forever."""
    setup_logging()

    logger.info("=" * 60)
    logger.info("Document Processing Worker starting...")
    logger.info(
        "  Kafka broker:  {broker}",
        broker=settings.KAFKA_BOOTSTRAP_SERVERS,
    )
    logger.info(
        "  Topic:         {topic}",
        topic=settings.KAFKA_DOCUMENT_TOPIC,
    )
    logger.info(
        "  Consumer group: {group}",
        group=settings.KAFKA_CONSUMER_GROUP,
    )
    logger.info(
        "  DLQ topic:     {dlq}",
        dlq=settings.KAFKA_DLQ_TOPIC,
    )
    logger.info(
        "  Max retries:   {retries}",
        retries=settings.DOCUMENT_MAX_RETRIES,
    )
    logger.info("=" * 60)

    consumer = KafkaConsumerService()

    # ── Graceful shutdown on SIGINT / SIGTERM ────────────────────────
    shutdown_event = asyncio.Event()

    def _signal_handler(sig, frame):
        logger.info("Shutdown signal received ({sig}), stopping...", sig=sig)
        shutdown_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        await consumer.start()

        # Run consumer in a task so we can wait for shutdown signal
        consumer_task = asyncio.create_task(
            consumer.consume_forever(handler=process_document)
        )

        # Wait for shutdown signal
        await shutdown_event.wait()

        # Stop consumer (breaks the consume loop)
        await consumer.stop()

        # Wait for consumer task to finish
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception as exc:
        logger.exception("Worker crashed: {error}", error=exc)
        sys.exit(1)
    finally:
        try:
            await consumer.stop()
        except Exception:
            pass
        logger.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
