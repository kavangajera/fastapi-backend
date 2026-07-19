"""
routes/temperature_logs.py
──────────────────────────
Basic temperature-logs API — a connectivity surface to confirm an external
temperature device can reach the backend and store readings.

`POST /temperature-logs`  — store a batch of readings from one device.
`GET  /temperature-logs`  — return all stored readings (newest first).

Deliberately **unauthenticated** and **not pharmacy-scoped** for now; auth and
pharmacy wiring come later.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from schemas.response_schema import Response_Schema, success_response
from schemas.temperature_log import TemperatureLogCreateInput, TemperatureLogOutput
from services.temperature_log_service import (
    create_temperature_logs,
    list_temperature_logs,
)

router = APIRouter(tags=["Temperature Logs"])


@router.post(
    "/temperature-logs",
    response_model=Response_Schema,
    summary="Store temperature logs from a device",
    description=(
        "Store an array of temperature readings reported by an external device. "
        "`temp_device_id` is the device's own hardware id (distinct from our "
        "internal device id). Each reading becomes its own row."
    ),
)
async def store_temperature_logs(
    body: TemperatureLogCreateInput,
    db: AsyncSession = Depends(get_async_db),
):
    count = await create_temperature_logs(body, db)
    return success_response(
        {"stored": count, "temp_device_id": body.temp_device_id},
        "Temperature logs stored successfully",
        201,
    )


@router.get(
    "/temperature-logs",
    response_model=Response_Schema,
    summary="Get all temperature logs",
    description=(
        "Return all stored temperature readings, newest first. Optionally filter "
        "by `temp_device_id`."
    ),
)
async def get_temperature_logs(
    temp_device_id: str | None = Query(
        None, description="Filter by external temperature device id."
    ),
    db: AsyncSession = Depends(get_async_db),
):
    rows = await list_temperature_logs(db, temp_device_id=temp_device_id)
    data = [
        TemperatureLogOutput.model_validate(row).model_dump(by_alias=False)
        for row in rows
    ]
    return success_response(data, "Temperature logs retrieved successfully")
