"""
routes/temperature_logs.py
──────────────────────────
The readings themselves.

    POST /temperature-logs           device pushes a batch (device session token)
    GET  /temperature-logs           pharmacy reads a page  (user token)
    GET  /temperature-logs/summary   per-device dashboard snapshot
    GET  /temperature-logs/{id}      one reading

The push is authenticated by a **device session token**, not a user token — see
`routes/temperature_devices.py` for how a device obtains one. The device's
identity, its session, and the owning pharmacy all come from that token, so a
batch can never claim to be from a device the caller does not hold the secret
for, and the payload carries only readings.

The reads are ordinary pharmacy-scoped user endpoints.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.config import settings
from core.enums import Feature
from middlewares.auth import auth_incoming_req, require_admin
from middlewares.device_auth import TemperatureDeviceContext, auth_temperature_device
from schemas.response_schema import Response_Schema, success_response
from schemas.system_internal_user_schema import System_Internal_User_Schema
from schemas.temperature_log import (
    TemperatureLogListOutput,
    TemperatureLogOutput,
    TemperaturePushOutput,
    TemperatureReadingInput,
    TemperatureSummaryOutput,
)
from services.feature_gate import ensure_feature
from services.pharmacy_authz import ensure_pharmacy_access
from services.temperature_log_service import (
    build_summary,
    get_temperature_log,
    ingest_readings,
    list_temperature_logs,
    resolve_device_names,
)

router = APIRouter(tags=["Temperature Logs"])


def _log_out(row, nickname: str | None = None) -> TemperatureLogOutput:
    out = TemperatureLogOutput.model_validate(row, from_attributes=True)
    out.device_nickname = nickname
    return out


# ─────────────────────────────────────────────────────────────────────
# Step 3 — the device pushes readings
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/temperature-logs",
    response_model=Response_Schema,
    status_code=201,
    summary="Push a batch of temperature readings",
    description=(
        "Send a **JSON array** of reading objects, authenticated with the "
        "device session token from `/temperature-devices/logging/start`:\n\n"
        "```\nAuthorization: Bearer <device session token>\n\n"
        '[{"time": "2026-08-25T10:00:00", "temp": 4.2},\n'
        ' {"time": "2026-08-25T10:05:00", "temp": 8.6}]\n```\n\n'
        "`temperature`/`temp`/`value` and `recorded_at`/`time`/`timestamp` are "
        "interchangeable, extra keys are preserved verbatim in the stored row's "
        "`raw_payload`, and `status` is derived from the safe range when the "
        "device does not send one. Each reading becomes its own row.\n\n"
        "401 with `data.reason` of `TOKEN_EXPIRED` means present the secret "
        "again for a new token; `SESSION_STOPPED` means logging was stopped."
    ),
)
async def push_temperature_logs(
    readings: list[TemperatureReadingInput] = Body(
        ...,
        min_length=1,
        description="Array of readings recorded since the last push.",
        examples=[
            [
                {"time": "2026-08-25T10:00:00", "temp": 4.2, "probe": "PRB-001"},
                {"time": "2026-08-25T10:05:00", "temp": 8.6, "probe": "PRB-001"},
            ]
        ],
    ),
    ctx: TemperatureDeviceContext = Depends(auth_temperature_device),
    db: AsyncSession = Depends(get_async_db),
):
    result = await ingest_readings(db, ctx, readings)
    return success_response(
        TemperaturePushOutput(**result).model_dump(by_alias=False),
        f"Stored {result['stored']} temperature readings",
        201,
    )


# ─────────────────────────────────────────────────────────────────────
# Pharmacy-side reads
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/temperature-logs/summary",
    response_model=Response_Schema,
    summary="Per-device temperature snapshot",
    description=(
        "One entry per registered device: its latest reading, whether it is "
        "currently logging, and min / max / average / excursion counts over the "
        "last `hours` hours. This is what the dashboard header card reads."
    ),
)
async def temperature_summary(
    medical_store_id: int = Query(..., description="Pharmacy to summarize."),
    hours: int = Query(24, ge=1, le=8760, description="Width of the statistics window."),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, medical_store_id)
    await ensure_feature(db, medical_store_id, Feature.TEMP_MONITORING_ALERTS)

    data = await build_summary(db, medical_store_id=medical_store_id, hours=hours)
    return success_response(
        TemperatureSummaryOutput(**data).model_dump(by_alias=False),
        "Temperature summary retrieved successfully",
    )


@router.get(
    "/temperature-logs",
    response_model=Response_Schema,
    summary="List temperature readings for a pharmacy",
    description=(
        "Readings for the store, newest first. Filter by device, logging "
        "session, status, or a `recorded_at` window."
    ),
)
async def get_temperature_logs(
    medical_store_id: int = Query(..., description="Pharmacy to read."),
    temperature_device_id: int | None = Query(None, description="Filter by device."),
    session_id: int | None = Query(None, description="Filter by logging session."),
    status: str | None = Query(None, description="Filter by status, e.g. Normal / High / Low."),
    date_from: datetime | None = Query(None, description="Earliest `recorded_at` (inclusive)."),
    date_to: datetime | None = Query(None, description="Latest `recorded_at` (inclusive)."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, medical_store_id)
    await ensure_feature(db, medical_store_id, Feature.TEMP_MONITORING_ALERTS)

    rows, total, names = await list_temperature_logs(
        db,
        medical_store_id=medical_store_id,
        temperature_device_id=temperature_device_id,
        session_id=session_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        skip=skip,
        limit=limit,
    )
    payload = TemperatureLogListOutput(
        pharmacy_id=medical_store_id,
        items=[_log_out(r, names.get(r.temperature_device_id)) for r in rows],
        total=total,
        skip=skip,
        limit=limit,
    )
    return success_response(
        payload.model_dump(by_alias=False), "Temperature logs retrieved successfully"
    )


@router.get(
    "/temperature-logs/{log_id}",
    response_model=Response_Schema,
    summary="Get one temperature reading",
    description="Includes the `raw_payload` the device originally sent.",
)
async def get_temperature_log_detail(
    log_id: int = Path(..., description="temperature_log_id"),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    row = await get_temperature_log(db, log_id)
    # Legacy rows predate pharmacy scoping; only ADMIN can see those.
    if row.medical_store_id is not None:
        await ensure_pharmacy_access(db, user, row.medical_store_id)
        await ensure_feature(db, row.medical_store_id, Feature.TEMP_MONITORING_ALERTS)
    else:
        await require_admin(user)

    nickname = None
    if row.temperature_device_id is not None:
        nickname = (await resolve_device_names(db, {row.temperature_device_id})).get(
            row.temperature_device_id
        )

    out = _log_out(row, nickname).model_dump(by_alias=False)
    out["safe_min_c"] = settings.TEMPERATURE_SAFE_MIN_C
    out["safe_max_c"] = settings.TEMPERATURE_SAFE_MAX_C
    return success_response(out, "Temperature reading retrieved successfully")
