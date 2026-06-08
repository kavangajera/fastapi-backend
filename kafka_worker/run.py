"""
kafka_worker/run.py
───────────────────
Entry point for a per-type document-processing worker.

Each worker process handles ONE process type and runs TWO concurrent
consumers:
    • the main consumer  (<type>-processing)
    • the retry consumer (<type>-retry, delayed re-injection)

Run (scale each type independently by launching more instances):
    python -m kafka_worker.run --type invoice
    python -m kafka_worker.run --type dispense
    python -m kafka_worker.run --type barcode

Requires the shared Kafka producer (for retries / DLQ / results), which
this process starts and stops itself.
"""

from __future__ import annotations

import argparse
import asyncio
import signal

from loguru import logger

from core.config import settings
from core.enums import ProcessType
from core.logging import setup_logging
from kafka_infra import topics
from kafka_infra.producer import kafka_producer
from kafka_worker.base_worker import Worker
from kafka_worker.retry_consumer import RetryConsumer


async def run_worker(process_type: ProcessType) -> None:
    setup_logging()

    logger.info("=" * 60)
    logger.info("Document Worker starting: type={type}", type=process_type.value)
    logger.info("  Broker:    {b}", b=settings.KAFKA_BOOTSTRAP_SERVERS)
    logger.info("  Main:      {t}", t=topics.main_topic(process_type))
    logger.info("  Retry:     {t}", t=topics.retry_topic(process_type))
    logger.info("  DLQ:       {t}", t=topics.dlq_topic(process_type))
    logger.info("  Results:   {t}", t=topics.results_topic())
    logger.info("  Max tries: {m}", m=settings.DOCUMENT_MAX_RETRIES)
    logger.info("=" * 60)

    # Ensure topics exist (idempotent); tolerate broker hiccups.
    try:
        await topics.ensure_topics()
    except Exception as exc:
        logger.warning("Topic ensure failed (continuing): {err}", err=exc)

    await kafka_producer.start()

    worker = Worker(process_type)
    retry = RetryConsumer(process_type)
    await worker.start()
    await retry.start()

    shutdown = asyncio.Event()

    def _signal_handler(*_a):
        logger.info("Shutdown signal received, stopping worker...")
        shutdown.set()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                # Windows: fall back to signal.signal
                signal.signal(sig, lambda *_a: shutdown.set())
    except Exception:
        pass

    worker_task = asyncio.create_task(worker.run())
    retry_task = asyncio.create_task(retry.run())

    await shutdown.wait()

    await worker.stop()
    await retry.stop()
    for task in (worker_task, retry_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await kafka_producer.stop()
    logger.info("Worker stopped cleanly: type={type}", type=process_type.value)


def main() -> None:
    parser = argparse.ArgumentParser(description="QueueRX document processing worker")
    parser.add_argument(
        "--type",
        required=True,
        choices=[pt.value for pt in ProcessType],
        help="Process type this worker handles",
    )
    args = parser.parse_args()
    asyncio.run(run_worker(ProcessType(args.type)))


if __name__ == "__main__":
    main()
