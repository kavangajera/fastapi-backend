"""
kafka_worker/retry_consumer.py
──────────────────────────────
Consumes a process type's ``<type>-retry`` topic and re-injects each job
into the main ``<type>-processing`` topic once its ``process_after``
delay has elapsed.

This keeps backoff OFF the main consumer: failed messages leave the main
partition immediately, wait here, then re-enter for another attempt.

Manual commit only — a job is committed in the retry topic ONLY after it
has been re-published to the main topic.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer
from loguru import logger

from core.config import settings
from core.enums import ProcessType
from kafka_infra import topics
from kafka_infra.messages import ProcessingJob
from kafka_infra.producer import kafka_producer


class RetryConsumer:
    """Delayed re-injection consumer for a single process type."""

    def __init__(self, process_type: ProcessType) -> None:
        self.process_type = process_type
        self.topic = topics.retry_topic(process_type)
        self.group = topics.retry_group(process_type)
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
            "Retry consumer started: type={type} topic={topic} group={group}",
            type=self.process_type.value,
            topic=self.topic,
            group=self.group,
        )

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None
            logger.info(
                "Retry consumer stopped: type={type}", type=self.process_type.value
            )

    async def run(self) -> None:
        if not self._consumer:
            raise RuntimeError("Retry consumer not started. Call start() first.")
        self._running = True
        try:
            async for msg in self._consumer:
                if not self._running:
                    break
                await self._reinject(msg.value)
                await self._consumer.commit()
        except asyncio.CancelledError:
            pass
        finally:
            logger.info(
                "Retry consumer loop exited: type={type}", type=self.process_type.value
            )

    async def _reinject(self, raw: dict) -> None:
        try:
            job = ProcessingJob(**raw)
        except Exception as exc:
            logger.error("Malformed retry job skipped: {raw} ({err})", raw=raw, err=exc)
            return

        # Honor the delay: sleep until process_after, if in the future.
        if job.process_after:
            try:
                due = datetime.fromisoformat(job.process_after)
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                wait = (due - datetime.now(timezone.utc)).total_seconds()
                if wait > 0:
                    logger.info(
                        "Retry waiting {wait:.1f}s: doc_key={dk} attempt={attempt}",
                        wait=wait,
                        dk=job.doc_key,
                        attempt=job.attempt,
                    )
                    await asyncio.sleep(wait)
            except ValueError:
                logger.warning("Bad process_after, re-injecting now: {val}", val=job.process_after)

        # Clear the delay marker and push back onto the main topic.
        job.process_after = None
        await kafka_producer.publish_job(job)
        logger.info(
            "Re-injected to main: doc_key={dk} attempt={attempt}",
            dk=job.doc_key,
            attempt=job.attempt,
        )
