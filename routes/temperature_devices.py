"""
routes/temperature_devices.py
─────────────────────────────
Two audiences share this router, and the split matters:

**Pharmacy users** (Bearer *user* token, `ensure_pharmacy_access` +
`ensure_feature`) manage the registry:

    POST   /temperature-devices                    register a logger
    GET    /temperature-devices                    list a store's loggers
    GET    /temperature-devices/{id}               one logger
    PATCH  /temperature-devices/{id}               rename / deactivate
    DELETE /temperature-devices/{id}               soft-delete (readings stay)
    GET    /temperature-devices/{id}/sessions      logging history
    POST   /temperature-devices/{id}/stop-logging  force-stop from the dashboard

**The device itself** (its secret, no user session) drives the lifecycle:

    POST   /temperature-devices/logging/start      → session + token
    POST   /temperature-devices/logging/token      → replacement token, same session
    POST   /temperature-devices/logging/stop       → session closed, token dead

The device-facing endpoints are deliberately unauthenticated in the *user*
sense — the secret is the credential. They are not feature-gated either: a
lapsed subscription should stop a pharmacy reading its data, not silently strand
a fridge logger that is already deployed.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.config import settings
from core.enums import Feature
from middlewares.auth import auth_incoming_req
from models import TemperatureDeviceSession
from schemas.response_schema import Response_Schema, success_response
from schemas.system_internal_user_schema import System_Internal_User_Schema
from schemas.temperature_device import (
    DeviceSecretInput,
    DeviceTokenOutput,
    StopLoggingOutput,
    TemperatureDeviceOutput,
    TemperatureDeviceRegisteredOutput,
    TemperatureDeviceRegisterInput,
    TemperatureDeviceUpdateInput,
    TemperatureSessionOutput,
)
from services.feature_gate import ensure_feature
from services.pharmacy_authz import ensure_pharmacy_access
from services.temperature_log_service import latest_reading_map
from services.temperature_device_service import (
    delete_device,
    get_active_session,
    get_active_sessions_for_store,
    get_device,
    issue_token,
    list_devices,
    register_device,
    resolve_device_by_secret,
    start_logging,
    stop_logging,
    update_device,
)

router = APIRouter(tags=["Temperature Devices"])


def _session_out(session) -> TemperatureSessionOutput | None:
    if session is None:
        return None
    return TemperatureSessionOutput.model_validate(session, from_attributes=True)


def _device_out(device, session=None, latest=None) -> TemperatureDeviceOutput:
    """Assemble the device payload.

    `is_logging`, `active_session` and the `latest_*` fields are not columns on
    the row — they come from the session and readings tables — so they have to
    be attached here after validation.
    """
    out = TemperatureDeviceOutput.model_validate(device, from_attributes=True)
    out.is_logging = session is not None
    out.active_session = _session_out(session)
    if latest is not None:
        out.latest_temperature = float(latest.temperature)
        out.latest_status = latest.status
    return out


def _token_out(device, session, token, expires_at, *, resumed: bool) -> DeviceTokenOutput:
    return DeviceTokenOutput(
        access_token=token,
        token_type="bearer",
        expires_at=expires_at,
        expires_in=settings.TEMPERATURE_DEVICE_TOKEN_EXPIRE_MINUTES * 60,
        session_id=session.session_id,
        temperature_device_id=device.temperature_device_id,
        pharmacy_id=device.medical_store_id,
        nickname=device.nickname,
        session_started_at=session.started_at,
        resumed=resumed,
    )


# ─────────────────────────────────────────────────────────────────────
# Step 1 — registration (pharmacy user)
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/temperature-devices",
    response_model=Response_Schema,
    status_code=201,
    summary="Register a temperature device",
    description=(
        "Register a logger against a pharmacy with a secret and a nickname. A "
        "pharmacy may register as many devices as it likes.\n\n"
        "Omit `device_secret` and the server generates a strong one and returns "
        "it **once** — it is stored hashed and can never be read back. Supply "
        "your own if the hardware already has a secret burned in."
    ),
)
async def register_temperature_device(
    body: TemperatureDeviceRegisterInput,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, body.medical_store_id)
    await ensure_feature(db, body.medical_store_id, Feature.TEMP_MONITORING_ALERTS)

    device, plaintext = await register_device(db, user, body)
    payload = TemperatureDeviceRegisteredOutput(
        device=_device_out(device),
        device_secret=plaintext,
        secret_generated=plaintext is not None,
    )
    return success_response(
        payload.model_dump(by_alias=False),
        "Temperature device registered successfully",
        201,
    )


@router.get(
    "/temperature-devices",
    response_model=Response_Schema,
    summary="List a pharmacy's temperature devices",
    description=(
        "Every logger registered to the store, newest first, each annotated "
        "with whether it is currently logging and the open session if so."
    ),
)
async def list_temperature_devices(
    medical_store_id: int = Query(..., description="Pharmacy to list devices for."),
    include_inactive: bool = Query(True, description="Include deactivated devices."),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, medical_store_id)
    await ensure_feature(db, medical_store_id, Feature.TEMP_MONITORING_ALERTS)

    devices = await list_devices(db, medical_store_id, include_inactive=include_inactive)
    sessions = await get_active_sessions_for_store(db, medical_store_id)
    latest = await latest_reading_map(db, [d.temperature_device_id for d in devices])
    data = [
        _device_out(
            d,
            sessions.get(d.temperature_device_id),
            latest.get(d.temperature_device_id),
        ).model_dump(by_alias=False)
        for d in devices
    ]
    return success_response(data, "Temperature devices retrieved successfully")


@router.get(
    "/temperature-devices/{temperature_device_id}",
    response_model=Response_Schema,
    summary="Get one temperature device",
)
async def get_temperature_device(
    temperature_device_id: int = Path(..., description="Device id."),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    device = await get_device(db, temperature_device_id)
    await ensure_pharmacy_access(db, user, device.medical_store_id)
    await ensure_feature(db, device.medical_store_id, Feature.TEMP_MONITORING_ALERTS)

    session = await get_active_session(db, device.temperature_device_id)
    latest = await latest_reading_map(db, [device.temperature_device_id])
    return success_response(
        _device_out(
            device, session, latest.get(device.temperature_device_id)
        ).model_dump(by_alias=False),
        "Temperature device retrieved successfully",
    )


@router.patch(
    "/temperature-devices/{temperature_device_id}",
    response_model=Response_Schema,
    summary="Rename or deactivate a temperature device",
    description=(
        "Setting `is_active` to false stops the device immediately: any open "
        "logging session is closed and its token stops being accepted."
    ),
)
async def patch_temperature_device(
    body: TemperatureDeviceUpdateInput,
    temperature_device_id: int = Path(..., description="Device id."),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    device = await get_device(db, temperature_device_id)
    await ensure_pharmacy_access(db, user, device.medical_store_id)
    await ensure_feature(db, device.medical_store_id, Feature.TEMP_MONITORING_ALERTS)

    device = await update_device(db, device, body)
    session = await get_active_session(db, device.temperature_device_id)
    latest = await latest_reading_map(db, [device.temperature_device_id])
    return success_response(
        _device_out(
            device, session, latest.get(device.temperature_device_id)
        ).model_dump(by_alias=False),
        "Temperature device updated successfully",
    )


@router.delete(
    "/temperature-devices/{temperature_device_id}",
    response_model=Response_Schema,
    summary="Delete a temperature device",
    description=(
        "Soft-deletes the device and closes any open session. The readings it "
        "produced are kept — they are the compliance record — and stay "
        "attributed to it."
    ),
)
async def remove_temperature_device(
    temperature_device_id: int = Path(..., description="Device id."),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    device = await get_device(db, temperature_device_id)
    await ensure_pharmacy_access(db, user, device.medical_store_id)
    await ensure_feature(db, device.medical_store_id, Feature.TEMP_MONITORING_ALERTS)

    await delete_device(db, device)
    return success_response(
        {"temperature_device_id": temperature_device_id},
        "Temperature device deleted successfully",
    )


@router.get(
    "/temperature-devices/{temperature_device_id}/sessions",
    response_model=Response_Schema,
    summary="Logging sessions for a device",
    description="Session history, newest first — each start/stop window and its reading count.",
)
async def list_device_sessions(
    temperature_device_id: int = Path(..., description="Device id."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    device = await get_device(db, temperature_device_id)
    await ensure_pharmacy_access(db, user, device.medical_store_id)
    await ensure_feature(db, device.medical_store_id, Feature.TEMP_MONITORING_ALERTS)

    rows = (
        (
            await db.execute(
                select(TemperatureDeviceSession)
                .where(
                    TemperatureDeviceSession.temperature_device_id == temperature_device_id
                )
                .order_by(TemperatureDeviceSession.session_id.desc())
                .offset(skip)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    data = [_session_out(r).model_dump(by_alias=False) for r in rows]
    return success_response(data, "Logging sessions retrieved successfully")


@router.post(
    "/temperature-devices/{temperature_device_id}/stop-logging",
    response_model=Response_Schema,
    summary="Stop a device's logging session (from the dashboard)",
    description=(
        "The pharmacy-side equivalent of the device calling "
        "`/temperature-devices/logging/stop` — useful when the device is "
        "unreachable. Closes the session and invalidates its token. Idempotent."
    ),
)
async def stop_device_logging(
    temperature_device_id: int = Path(..., description="Device id."),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    device = await get_device(db, temperature_device_id)
    await ensure_pharmacy_access(db, user, device.medical_store_id)
    await ensure_feature(db, device.medical_store_id, Feature.TEMP_MONITORING_ALERTS)

    session = await stop_logging(db, device, reason="pharmacy_stop")
    payload = StopLoggingOutput(
        stopped=session is not None,
        already_stopped=session is None,
        session=_session_out(session),
    )
    return success_response(
        payload.model_dump(by_alias=False),
        "Logging stopped" if session else "Device was not logging",
    )


# ─────────────────────────────────────────────────────────────────────
# Steps 2, 4, 5 — session lifecycle (the device, using its secret)
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/temperature-devices/logging/start",
    response_model=Response_Schema,
    summary="Start logging — exchange a device secret for a session token",
    description=(
        "The device presents the secret it was registered with and gets back a "
        "session token to push readings with. The token is longer-lived than a "
        "user access token so an unattended logger is not re-authenticating "
        "constantly.\n\n"
        "Calling this while a session is already open **resumes** it (a logger "
        "that reboots continues the same run) and returns a fresh token; the "
        "previous token is revoked either way."
    ),
)
async def start_device_logging(
    body: DeviceSecretInput = Body(...),
    db: AsyncSession = Depends(get_async_db),
):
    device, session, token, expires_at, resumed = await start_logging(db, body.device_secret)
    return success_response(
        _token_out(device, session, token, expires_at, resumed=resumed).model_dump(
            by_alias=False
        ),
        "Logging resumed" if resumed else "Logging started",
    )


@router.post(
    "/temperature-devices/logging/token",
    response_model=Response_Schema,
    summary="Renew an expired session token with the device secret",
    description=(
        "The device's token has expired; it presents the secret again and gets "
        "a replacement for the **same** logging session, so the run is "
        "uninterrupted.\n\n"
        "Returns 409 if logging was stopped — the device should call "
        "`/temperature-devices/logging/start` rather than silently resuming."
    ),
)
async def renew_device_token(
    body: DeviceSecretInput = Body(...),
    db: AsyncSession = Depends(get_async_db),
):
    device, session, token, expires_at = await issue_token(db, body.device_secret)
    return success_response(
        _token_out(device, session, token, expires_at, resumed=True).model_dump(
            by_alias=False
        ),
        "Device token renewed",
    )


@router.post(
    "/temperature-devices/logging/stop",
    response_model=Response_Schema,
    summary="Stop logging — invalidate the device's current token",
    description=(
        "Closes the open logging session and invalidates the token issued "
        "against it, so any further push is rejected. Takes the secret rather "
        "than the token, so a device can still stop cleanly after its token "
        "expired. Idempotent."
    ),
)
async def stop_device_logging_with_secret(
    body: DeviceSecretInput = Body(...),
    db: AsyncSession = Depends(get_async_db),
):
    device = await resolve_device_by_secret(db, body.device_secret)
    session = await stop_logging(db, device, reason="device_stop")
    payload = StopLoggingOutput(
        stopped=session is not None,
        already_stopped=session is None,
        session=_session_out(session),
    )
    return success_response(
        payload.model_dump(by_alias=False),
        "Logging stopped" if session else "Device was not logging",
    )
