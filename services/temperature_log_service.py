"""
services/temperature_log_service.py
───────────────────────────────────
Write and read side of the temperature readings themselves.

Writes only ever happen through ``ingest_readings``, which takes an
authenticated device context — so a reading's device, session, and pharmacy
are taken from the token rather than the payload and cannot be spoofed.

Reads are pharmacy-scoped and paginated. Device nicknames are resolved with a
separate lookup rather than a join: the device may have been soft-deleted while
its readings live on (they are the compliance record), and an ORM join would
have the soft-delete filter drop those rows entirely.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.datetime_utils import to_naive_utc
from core.enums import TemperatureReadingStatus
from middlewares.device_auth import TemperatureDeviceContext
from models import TemperatureDevice, TemperatureLog
from schemas.temperature_log import TemperatureReadingInput
from services.temperature_device_service import get_active_sessions_for_store


def _raise(status_code: int, message: str, data=None):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": data},
    )


def derive_status(temperature: float) -> str:
    """Band a reading against the configured safe range."""
    if temperature < settings.TEMPERATURE_SAFE_MIN_C:
        return TemperatureReadingStatus.LOW.value
    if temperature > settings.TEMPERATURE_SAFE_MAX_C:
        return TemperatureReadingStatus.HIGH.value
    return TemperatureReadingStatus.NORMAL.value


# ─────────────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────────────


async def ingest_readings(
    db: AsyncSession,
    ctx: TemperatureDeviceContext,
    readings: list[TemperatureReadingInput],
) -> dict:
    """Store one pushed batch. Returns the acknowledgement payload."""
    if not readings:
        _raise(422, "Batch contained no readings")
    if len(readings) > settings.TEMPERATURE_LOG_MAX_BATCH_SIZE:
        _raise(
            413,
            f"Batch too large: {len(readings)} readings, "
            f"maximum is {settings.TEMPERATURE_LOG_MAX_BATCH_SIZE}",
        )

    device, session = ctx.device, ctx.session
    received_at = datetime.utcnow()
    # Fall back to the registry id when the device reports no hardware id of
    # its own, so the column is always meaningful.
    fallback_hw_id = str(device.temperature_device_id)

    rows: list[TemperatureLog] = []
    latest_recorded_at: datetime | None = None
    for reading in readings:
        temperature = float(reading.temperature)
        recorded_at = reading.recorded_at or received_at
        if latest_recorded_at is None or recorded_at > latest_recorded_at:
            latest_recorded_at = recorded_at
        rows.append(
            TemperatureLog(
                temp_device_id=reading.temp_device_id or fallback_hw_id,
                temperature=temperature,
                recorded_at=recorded_at,
                probe=reading.probe,
                status=reading.status or derive_status(temperature),
                temperature_device_id=device.temperature_device_id,
                session_id=session.session_id,
                medical_store_id=device.medical_store_id,
                raw_payload=reading.raw_payload,
            )
        )

    session.readings_count = (session.readings_count or 0) + len(rows)
    session.last_reading_at = latest_recorded_at
    device.total_readings = (device.total_readings or 0) + len(rows)
    device.last_reading_at = latest_recorded_at
    device.last_seen_at = received_at

    try:
        db.add_all(rows)
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to store temperature logs: {err}", err=str(exc))
        _raise(500, "Failed to store temperature logs")

    logger.info(
        "Stored {n} temperature readings for device {id} (session {sid})",
        n=len(rows),
        id=device.temperature_device_id,
        sid=session.session_id,
    )
    return {
        "stored": len(rows),
        "temperature_device_id": device.temperature_device_id,
        "session_id": session.session_id,
        "session_readings_count": session.readings_count,
        "token_expires_at": session.token_expires_at,
    }


# ─────────────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────────────


def _filters(
    *,
    medical_store_id: int,
    temperature_device_id: int | None,
    session_id: int | None,
    status: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
):
    """Predicates shared by the list and count queries.

    ``IsDeleted`` is spelled out rather than left to the global soft-delete
    listener, which only rewrites statements that select ORM entities — the
    ``count()`` below does not.
    """
    # An aware bound would be rendered with its offset and compared against a
    # naive column; pin both ends to naive UTC first.
    date_from = to_naive_utc(date_from)
    date_to = to_naive_utc(date_to)

    clauses = [
        TemperatureLog.medical_store_id == medical_store_id,
        TemperatureLog.IsDeleted.is_(False),
    ]
    if temperature_device_id is not None:
        clauses.append(TemperatureLog.temperature_device_id == temperature_device_id)
    if session_id is not None:
        clauses.append(TemperatureLog.session_id == session_id)
    if status:
        clauses.append(TemperatureLog.status == status)
    if date_from is not None:
        clauses.append(TemperatureLog.recorded_at >= date_from)
    if date_to is not None:
        clauses.append(TemperatureLog.recorded_at <= date_to)
    return clauses


async def resolve_device_names(db: AsyncSession, device_ids: set[int]) -> dict[int, str]:
    """Resolve device labels, including for soft-deleted devices."""
    ids = {i for i in device_ids if i is not None}
    if not ids:
        return {}
    result = await db.execute(
        select(TemperatureDevice.temperature_device_id, TemperatureDevice.nickname)
        .where(TemperatureDevice.temperature_device_id.in_(ids))
        .execution_options(include_deleted=True)
    )
    return {row[0]: row[1] for row in result.all()}


async def latest_reading_map(
    db: AsyncSession, device_ids: list[int]
) -> dict[int, TemperatureLog]:
    """Newest reading per device, keyed by device id.

    "Newest" follows the device clock (``recorded_at``), with the row id
    breaking ties, so it matches the ordering the readings list uses. One query
    per device: a pharmacy has a handful of fridges, not thousands, and the
    single-statement alternatives need either window functions or a correlated
    subquery that MySQL 5.7 optimizes poorly.
    """
    out: dict[int, TemperatureLog] = {}
    for device_id in device_ids:
        row = (
            await db.execute(
                select(TemperatureLog)
                .where(
                    TemperatureLog.temperature_device_id == device_id,
                    TemperatureLog.IsDeleted.is_(False),
                )
                .order_by(TemperatureLog.recorded_at.desc(), TemperatureLog.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if row is not None:
            out[device_id] = row
    return out


async def list_temperature_logs(
    db: AsyncSession,
    *,
    medical_store_id: int,
    temperature_device_id: int | None = None,
    session_id: int | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[TemperatureLog], int, dict[int, str]]:
    """A page of readings, newest first, plus the total and device labels."""
    clauses = _filters(
        medical_store_id=medical_store_id,
        temperature_device_id=temperature_device_id,
        session_id=session_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )

    total = (
        await db.execute(select(func.count()).select_from(TemperatureLog).where(*clauses))
    ).scalar_one()

    result = await db.execute(
        select(TemperatureLog)
        .where(*clauses)
        # recorded_at is device-reported and may be NULL on legacy rows; id
        # breaks ties so pagination is stable.
        .order_by(TemperatureLog.recorded_at.desc(), TemperatureLog.id.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = list(result.scalars().all())
    names = await resolve_device_names(db, {r.temperature_device_id for r in rows})
    return rows, total, names


async def get_temperature_log(db: AsyncSession, log_id: int) -> TemperatureLog:
    row = (
        await db.execute(select(TemperatureLog).where(TemperatureLog.id == log_id))
    ).scalar_one_or_none()
    if row is None:
        _raise(404, "Temperature reading not found")
    return row


async def build_summary(
    db: AsyncSession, *, medical_store_id: int, hours: int = 24
) -> dict:
    """Per-device snapshot for the dashboard: latest reading + window stats."""
    since = datetime.utcnow() - timedelta(hours=hours)

    devices = (
        (
            await db.execute(
                select(TemperatureDevice)
                .where(TemperatureDevice.medical_store_id == medical_store_id)
                .order_by(TemperatureDevice.temperature_device_id.desc())
            )
        )
        .scalars()
        .all()
    )
    sessions = await get_active_sessions_for_store(db, medical_store_id)

    # Window aggregates for every device in one pass.
    agg_rows = (
        await db.execute(
            select(
                TemperatureLog.temperature_device_id,
                func.count().label("n"),
                func.min(TemperatureLog.temperature).label("min_t"),
                func.max(TemperatureLog.temperature).label("max_t"),
                func.avg(TemperatureLog.temperature).label("avg_t"),
            )
            .where(
                TemperatureLog.medical_store_id == medical_store_id,
                TemperatureLog.IsDeleted.is_(False),
                TemperatureLog.recorded_at >= since,
            )
            .group_by(TemperatureLog.temperature_device_id)
        )
    ).all()
    aggs = {r[0]: r for r in agg_rows}

    excursion_rows = (
        await db.execute(
            select(TemperatureLog.temperature_device_id, func.count().label("n"))
            .where(
                TemperatureLog.medical_store_id == medical_store_id,
                TemperatureLog.IsDeleted.is_(False),
                TemperatureLog.recorded_at >= since,
                (TemperatureLog.temperature < settings.TEMPERATURE_SAFE_MIN_C)
                | (TemperatureLog.temperature > settings.TEMPERATURE_SAFE_MAX_C),
            )
            .group_by(TemperatureLog.temperature_device_id)
        )
    ).all()
    excursions = {r[0]: r[1] for r in excursion_rows}

    latest_by_device = await latest_reading_map(
        db, [d.temperature_device_id for d in devices]
    )

    out = []
    for device in devices:
        latest = latest_by_device.get(device.temperature_device_id)
        session = sessions.get(device.temperature_device_id)
        agg = aggs.get(device.temperature_device_id)
        out.append(
            {
                "temperature_device_id": device.temperature_device_id,
                "nickname": device.nickname,
                "is_active": device.is_active,
                "is_logging": session is not None,
                "session_id": session.session_id if session else None,
                "session_started_at": session.started_at if session else None,
                "token_expires_at": session.token_expires_at if session else None,
                "last_seen_at": device.last_seen_at,
                "latest_temperature": float(latest.temperature) if latest else None,
                "latest_recorded_at": latest.recorded_at if latest else None,
                "latest_status": latest.status if latest else None,
                "latest_probe": latest.probe if latest else None,
                "total_readings": device.total_readings or 0,
                "readings_in_window": int(agg[1]) if agg else 0,
                "min_temperature": float(agg[2]) if agg and agg[2] is not None else None,
                "max_temperature": float(agg[3]) if agg and agg[3] is not None else None,
                "avg_temperature": round(float(agg[4]), 2) if agg and agg[4] is not None else None,
                "excursions_in_window": int(excursions.get(device.temperature_device_id, 0)),
            }
        )

    return {
        "pharmacy_id": medical_store_id,
        "hours": hours,
        "safe_min_c": settings.TEMPERATURE_SAFE_MIN_C,
        "safe_max_c": settings.TEMPERATURE_SAFE_MAX_C,
        "devices": out,
    }
