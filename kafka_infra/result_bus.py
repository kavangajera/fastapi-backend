"""
kafka_infra/result_bus.py
─────────────────────────
In-API result correlation for the async-await upload UX.

The upload endpoint publishes a job, then awaits the worker's result
*without polling*. This module bridges the gap:

    1. Upload handler calls `register(doc_key)` → gets an asyncio.Future.
    2. A background consumer (started in the FastAPI lifespan) reads the
       shared `processing-results` topic and calls `resolve(result)`,
       which completes the matching Future.
    3. Upload handler `await`s the Future (with timeout).

Each API instance joins a UNIQUE consumer group so every instance
receives every result (broadcast), and only resolves the doc_keys it is
locally awaiting. `auto_offset_reset="latest"` — we only care about
results produced after this instance started awaiting.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from aiokafka import AIOKafkaConsumer
from loguru import logger

from core.config import settings
from kafka_infra import topics
from kafka_infra.messages import ProcessingResult


class ResultBus:
    """Singleton that correlates worker results back to awaiting requests."""

    def __init__(self) -> None:
        self._futures: dict[str, asyncio.Future[ProcessingResult]] = {}
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task | None = None
        self._running = False

    # ── Awaiting side (called by the upload handler) ─────────────────

    def register(self, doc_key: str) -> asyncio.Future[ProcessingResult]:
        """Register interest in a doc_key; returns a Future to await."""
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[ProcessingResult] = loop.create_future()
        self._futures[doc_key] = fut
        return fut

    def unregister(self, doc_key: str) -> None:
        """Drop a registration (e.g. on timeout) to avoid leaks."""
        self._futures.pop(doc_key, None)

    def _resolve(self, result: ProcessingResult) -> None:
        fut = self._futures.pop(result.doc_key, None)
        if fut and not fut.done():
            fut.set_result(result)

    # ── Consumer lifecycle (called by FastAPI lifespan) ──────────────

    async def start(self) -> None:
        """Start the background results consumer."""
        group_id = f"api-results-{uuid.uuid4().hex[:8]}"
        self._consumer = AIOKafkaConsumer(
            topics.results_topic(),
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            enable_auto_commit=True,
            auto_offset_reset="latest",
        )
        await self._consumer.start()
        self._running = True
        self._task = asyncio.create_task(self._consume_loop())
        logger.info(
            "Result bus started: topic={topic} group={group}",
            topic=topics.results_topic(),
            group=group_id,
        )

    async def stop(self) -> None:
        """Stop the consumer and fail any outstanding futures."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None
        # Don't leave awaiters hanging on shutdown.
        for fut in self._futures.values():
            if not fut.done():
                fut.cancel()
        self._futures.clear()
        logger.info("Result bus stopped")

    async def _consume_loop(self) -> None:
        assert self._consumer is not None
        try:
            async for msg in self._consumer:
                if not self._running:
                    break
                try:
                    result = ProcessingResult(**msg.value)
                except Exception as exc:
                    logger.warning("Bad result message skipped: {error}", error=exc)
                    continue
                self._resolve(result)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception("Result bus consume loop crashed: {error}", error=exc)


# ── Module-level singleton ──────────────────────────────────────────────────
result_bus = ResultBus()
