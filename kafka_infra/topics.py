"""
kafka_infra/topics.py
─────────────────────
Single source of truth for Kafka topic naming and creation.

Topic families (one per ProcessType):
    <type>-processing   main job topic        (consumed by the <type> worker)
    <type>-retry        delayed retry topic   (consumed by the retry consumer)
    <type>-dlq          dead letter queue     (terminal failures)

Shared:
    processing-results  worker → API result bus (async-await UX)

Consumer groups:
    <type>-workers        main worker group  (horizontal scaling)
    <type>-retry-workers  retry consumer group
"""

from __future__ import annotations

from core.config import settings
from core.enums import ProcessType


# ── Topic-name derivation ────────────────────────────────────────────────────

def main_topic(process_type: ProcessType | str) -> str:
    return f"{ProcessType(process_type).value}-processing"


def retry_topic(process_type: ProcessType | str) -> str:
    return f"{ProcessType(process_type).value}-retry"


def dlq_topic(process_type: ProcessType | str) -> str:
    return f"{ProcessType(process_type).value}-dlq"


def results_topic() -> str:
    return settings.KAFKA_RESULTS_TOPIC


# ── Consumer-group derivation ────────────────────────────────────────────────

def worker_group(process_type: ProcessType | str) -> str:
    return f"{ProcessType(process_type).value}-workers"


def retry_group(process_type: ProcessType | str) -> str:
    return f"{ProcessType(process_type).value}-retry-workers"


def all_topics() -> list[str]:
    """Every topic this system uses — handy for admin creation."""
    topics: list[str] = [results_topic()]
    for pt in ProcessType:
        topics.extend([main_topic(pt), retry_topic(pt), dlq_topic(pt)])
    return topics


async def ensure_topics() -> None:
    """
    Create all required topics if they don't exist.

    Idempotent — safe to call repeatedly. In dev the broker has
    auto-create enabled, but explicit creation guarantees the right
    partition count and avoids first-message races in production.
    """
    from aiokafka.admin import AIOKafkaAdminClient, NewTopic
    from aiokafka.errors import TopicAlreadyExistsError
    from loguru import logger

    admin = AIOKafkaAdminClient(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
    )
    await admin.start()
    try:
        existing = set(await admin.list_topics())
        new_topics = [
            NewTopic(
                name=name,
                num_partitions=settings.KAFKA_NUM_PARTITIONS,
                replication_factor=settings.KAFKA_REPLICATION_FACTOR,
            )
            for name in all_topics()
            if name not in existing
        ]
        if not new_topics:
            logger.info("All Kafka topics already exist.")
            return
        try:
            await admin.create_topics(new_topics)
            logger.info(
                "Created Kafka topics: {names}",
                names=[t.name for t in new_topics],
            )
        except TopicAlreadyExistsError:
            logger.info("Topics already existed (race), continuing.")
    finally:
        await admin.close()
