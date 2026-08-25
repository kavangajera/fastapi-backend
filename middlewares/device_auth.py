"""
middlewares/device_auth.py
──────────────────────────
Bearer gate for **temperature devices**, the machine equivalent of
``middlewares/auth.py``:

    ctx: TemperatureDeviceContext = Depends(auth_temperature_device)

A device token is only honoured while all four of these hold:

1. the JWT verifies, has not passed its ``exp``, and carries the device scope;
2. the logging session it names is still ACTIVE;
3. its ``jti`` is still the session's ``current_jti`` — so minting a new token
   (or stopping the session, which NULLs the column) revokes the old one
   immediately, which is what "stop logging invalidates the current token"
   means in practice;
4. the device itself is still registered and active.

Every failure is a 401 carrying a machine-readable ``reason`` in ``data`` so
firmware can tell "get a new token" apart from "stop trying".
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import TemperatureSessionStatus
from core.security_schemes import verify_device_token
from models import TemperatureDevice, TemperatureDeviceSession

# Declared separately from the user-facing `security` scheme so Swagger shows
# device endpoints as taking their own credential.
device_security = HTTPBearer(
    scheme_name="TemperatureDeviceToken",
    description="Session token from POST /temperature-devices/logging/start.",
)


@dataclass
class TemperatureDeviceContext:
    """What an authenticated device is allowed to write against."""

    device: TemperatureDevice
    session: TemperatureDeviceSession
    jti: str

    @property
    def temperature_device_id(self) -> int:
        return self.device.temperature_device_id

    @property
    def medical_store_id(self) -> int:
        return self.device.medical_store_id


def _unauthorized(message: str, reason: str) -> None:
    raise HTTPException(
        status_code=401,
        detail={"status_code": 401, "message": message, "data": {"reason": reason}},
    )


async def auth_temperature_device(
    db: AsyncSession = Depends(get_async_db),
    credentials: HTTPAuthorizationCredentials = Depends(device_security),
) -> TemperatureDeviceContext:
    data = verify_device_token(credentials.credentials)

    session_id = data.get("session_id")
    jti = data.get("jti")
    device_id = data.get("temperature_device_id")
    if not session_id or not jti or not device_id:
        _unauthorized("Malformed device token", "TOKEN_INVALID")

    session = (
        await db.execute(
            select(TemperatureDeviceSession).where(
                TemperatureDeviceSession.session_id == session_id
            )
        )
    ).scalar_one_or_none()
    if session is None:
        _unauthorized("Logging session no longer exists", "SESSION_GONE")

    if session.status != TemperatureSessionStatus.ACTIVE.value:
        _unauthorized(
            "Logging has been stopped for this device. Start logging again to resume.",
            "SESSION_STOPPED",
        )

    if session.current_jti != jti:
        # A newer token was issued for this session, or the session was
        # stopped and restarted. Either way this one is dead.
        _unauthorized(
            "This device token has been superseded. Re-authenticate with the device secret.",
            "TOKEN_REVOKED",
        )

    device = (
        await db.execute(
            select(TemperatureDevice).where(
                TemperatureDevice.temperature_device_id == session.temperature_device_id
            )
        )
    ).scalar_one_or_none()
    if device is None:
        _unauthorized("Device is no longer registered", "DEVICE_GONE")

    if not device.is_active:
        _unauthorized("Device has been deactivated", "DEVICE_INACTIVE")

    return TemperatureDeviceContext(device=device, session=session, jti=jti)
