"""
scripts/wipe_db.py
──────────────────
Drop every table in the configured database. Use before re-baselining
Alembic to a single initial migration.

Usage:
    uv run python -m scripts.wipe_db
"""

from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import settings


async def wipe() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        rows = await conn.execute(text("SHOW TABLES"))
        tables = [r[0] for r in rows.fetchall()]
        for name in tables:
            logger.info("DROP TABLE `{name}`", name=name)
            await conn.execute(text(f"DROP TABLE IF EXISTS `{name}`"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    await engine.dispose()
    logger.info("Wiped {n} table(s).", n=len(tables))


if __name__ == "__main__":
    asyncio.run(wipe())
