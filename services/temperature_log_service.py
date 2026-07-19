"""
services/temperature_log_service.py
───────────────────────────────────
DB create + list for the basic temperature-logs API.

One reading → one ``TemperatureLog`` row. No pharmacy scoping and no
record-id sync stamping yet (``record_Identifier`` stays NULL, which the
AuditMixin explicitly allows) — this is a basic connectivity surface.
"""

from __future__ import annotations

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models import TemperatureLog
from schemas.temperature_log import TemperatureLogCreateInput


async def create_temperature_logs(
    body: TemperatureLogCreateInput, db: AsyncSession
) -> int:
    """Insert one row per reading; return the number stored."""
    rows = [
        TemperatureLog(
            temp_device_id=body.temp_device_id,
            temperature=reading.temperature,
            recorded_at=reading.recorded_at,
            probe=reading.probe,
            status=reading.status,
        )
        for reading in body.logs
    ]
    try:
        db.add_all(rows)
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to store temperature logs: {err}", err=str(exc))
        raise HTTPException(status_code=500, detail="Failed to store temperature logs")
    return len(rows)


async def list_temperature_logs(
    db: AsyncSession, *, temp_device_id: str | None = None
) -> list[TemperatureLog]:
    """Return all readings (newest first), optionally filtered by device."""
    stmt = select(TemperatureLog).order_by(TemperatureLog.created_at.desc())
    if temp_device_id:
        stmt = stmt.where(TemperatureLog.temp_device_id == temp_device_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
