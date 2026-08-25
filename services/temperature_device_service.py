"""
services/temperature_device_service.py
──────────────────────────────────────
The temperature-logging lifecycle, end to end.

    register_device        pharmacy user registers a logger (secret, nickname, store)
    start_logging          device presents its secret  → session opens, token minted
    issue_token            device presents its secret  → new token, same session
    stop_logging           device or pharmacy stops    → session closed, token dead

Secret handling
    Secrets are never stored in the clear. ``secret_lookup`` (SHA-256) is how a
    presented secret is *found* — an Argon2 hash is salted and therefore not
    searchable — and ``secret_hash`` (Argon2id) is what actually authenticates
    it. The SHA-256 index is unique, so no two devices can share a secret.

Token revocation
    The session row owns exactly one live token at a time (``current_jti``).
    Minting a token overwrites it; stopping the session NULLs it. Anything
    presenting a stale jti is rejected in ``middlewares/device_auth.py``.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.enums import TemperatureSessionStatus
from core.security_schemes import create_device_token
from models import TemperatureDevice, TemperatureDeviceSession
from schemas.system_internal_user_schema import System_Internal_User_Schema
from schemas.temperature_device import (
    TemperatureDeviceRegisterInput,
    TemperatureDeviceUpdateInput,
)

_hasher = PasswordHasher()


def _raise(status_code: int, message: str, data=None):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": data},
    )


def _now() -> datetime:
    # Naive UTC, matching the convention used across the codebase.
    return datetime.utcnow()


def _secret_lookup(secret: str) -> str:
    """Deterministic, searchable index for a secret."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _generate_secret() -> str:
    """A secret strong enough that the SHA-256 index alone would be safe."""
    return f"tdev_{secrets.token_urlsafe(32)}"


def _hint(secret: str) -> str:
    return secret[-4:] if len(secret) >= 4 else "****"


# ─────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────


async def register_device(
    db: AsyncSession,
    user: System_Internal_User_Schema,
    body: TemperatureDeviceRegisterInput,
) -> tuple[TemperatureDevice, str | None]:
    """Create a device row. Returns ``(device, plaintext_secret_if_generated)``.

    The plaintext is handed back **only** when we generated it — a
    caller-supplied secret is already in the caller's hands and echoing it
    would put it in logs and network traces for no benefit.
    """
    generated = body.device_secret is None
    secret = body.device_secret or _generate_secret()

    if len(secret) < settings.TEMPERATURE_DEVICE_SECRET_MIN_LENGTH:
        _raise(
            400,
            "Device secret must be at least "
            f"{settings.TEMPERATURE_DEVICE_SECRET_MIN_LENGTH} characters",
        )

    device = TemperatureDevice(
        medical_store_id=body.medical_store_id,
        nickname=body.nickname.strip(),
        secret_lookup=_secret_lookup(secret),
        secret_hash=_hasher.hash(secret),
        secret_hint=_hint(secret),
        is_active=True,
        registered_by_user_id=user.user_id,
    )
    try:
        db.add(device)
        await db.commit()
        await db.refresh(device)
    except IntegrityError:
        await db.rollback()
        # The only unique column a caller can collide on is secret_lookup.
        _raise(409, "That device secret is already in use. Choose a different one.")
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to register temperature device: {err}", err=str(exc))
        _raise(500, "Failed to register device")

    logger.info(
        "Registered temperature device {id} ({nick}) for store {store}",
        id=device.temperature_device_id,
        nick=device.nickname,
        store=device.medical_store_id,
    )
    return device, (secret if generated else None)


async def get_device(db: AsyncSession, temperature_device_id: int) -> TemperatureDevice:
    device = (
        await db.execute(
            select(TemperatureDevice).where(
                TemperatureDevice.temperature_device_id == temperature_device_id
            )
        )
    ).scalar_one_or_none()
    if device is None:
        _raise(404, "Temperature device not found")
    return device


async def list_devices(
    db: AsyncSession, medical_store_id: int, *, include_inactive: bool = True
) -> list[TemperatureDevice]:
    stmt = select(TemperatureDevice).where(
        TemperatureDevice.medical_store_id == medical_store_id
    )
    if not include_inactive:
        stmt = stmt.where(TemperatureDevice.is_active.is_(True))
    result = await db.execute(stmt.order_by(TemperatureDevice.temperature_device_id.desc()))
    return list(result.scalars().all())


async def update_device(
    db: AsyncSession, device: TemperatureDevice, body: TemperatureDeviceUpdateInput
) -> TemperatureDevice:
    if body.nickname is not None:
        device.nickname = body.nickname.strip()
    if body.is_active is not None and body.is_active != device.is_active:
        device.is_active = body.is_active
        if not body.is_active:
            # Deactivating must also cut any live token, or the device keeps
            # writing until its token happens to expire.
            await _close_active_sessions(db, device, reason="device_deactivated")
    try:
        await db.commit()
        await db.refresh(device)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to update temperature device: {err}", err=str(exc))
        _raise(500, "Failed to update device")
    return device


async def delete_device(db: AsyncSession, device: TemperatureDevice) -> None:
    """Soft-delete the device and cut any live session.

    The readings it produced stay — they are the compliance record — and keep
    their ``temperature_device_id`` link, which is why the soft delete matters:
    the device row must remain resolvable for display.
    """
    await _close_active_sessions(db, device, reason="device_deleted")
    device.IsDeleted = True
    device.is_active = False
    try:
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to delete temperature device: {err}", err=str(exc))
        _raise(500, "Failed to delete device")


# ─────────────────────────────────────────────────────────────────────
# Sessions
# ─────────────────────────────────────────────────────────────────────


async def get_active_session(
    db: AsyncSession, temperature_device_id: int
) -> TemperatureDeviceSession | None:
    """The device's open logging session, if it has one."""
    result = await db.execute(
        select(TemperatureDeviceSession)
        .where(
            TemperatureDeviceSession.temperature_device_id == temperature_device_id,
            TemperatureDeviceSession.status == TemperatureSessionStatus.ACTIVE.value,
        )
        .order_by(TemperatureDeviceSession.session_id.desc())
    )
    return result.scalars().first()


async def get_active_sessions_for_store(
    db: AsyncSession, medical_store_id: int
) -> dict[int, TemperatureDeviceSession]:
    """Open sessions for a whole store, keyed by device id (one query)."""
    result = await db.execute(
        select(TemperatureDeviceSession)
        .where(
            TemperatureDeviceSession.medical_store_id == medical_store_id,
            TemperatureDeviceSession.status == TemperatureSessionStatus.ACTIVE.value,
        )
        .order_by(TemperatureDeviceSession.session_id.asc())
    )
    # Ascending order + overwrite leaves the newest session per device winning.
    return {s.temperature_device_id: s for s in result.scalars().all()}


async def _close_active_sessions(
    db: AsyncSession, device: TemperatureDevice, *, reason: str
) -> None:
    """Mark every open session for the device stopped. Caller commits."""
    await db.execute(
        update(TemperatureDeviceSession)
        .where(
            TemperatureDeviceSession.temperature_device_id == device.temperature_device_id,
            TemperatureDeviceSession.status == TemperatureSessionStatus.ACTIVE.value,
        )
        .values(
            status=TemperatureSessionStatus.STOPPED.value,
            ended_at=_now(),
            end_reason=reason,
            current_jti=None,  # ← the live token dies here
        )
    )


async def resolve_device_by_secret(db: AsyncSession, device_secret: str) -> TemperatureDevice:
    """Find and authenticate a device from a presented secret, or raise 401.

    The row is locked (``FOR UPDATE``) because every caller goes on to read or
    change that device's session state. Without the lock two simultaneous
    start-logging calls could each see "no active session", create one, and
    leave the device with **two** ACTIVE sessions — each holding a token its own
    row considers current. That would quietly break the one-live-token-per-device
    guarantee the whole revocation scheme rests on. These calls are rare (start /
    renew / stop, not the push path), so serializing them per device is cheap.
    """
    device = (
        await db.execute(
            select(TemperatureDevice)
            .where(TemperatureDevice.secret_lookup == _secret_lookup(device_secret))
            .with_for_update()
        )
    ).scalar_one_or_none()

    if device is None:
        _raise(401, "Invalid device secret", {"reason": "SECRET_INVALID"})

    try:
        _hasher.verify(device.secret_hash, device_secret)
    except VerifyMismatchError:
        # Only reachable on a SHA-256 collision or a tampered row; treat it
        # exactly like an unknown secret.
        _raise(401, "Invalid device secret", {"reason": "SECRET_INVALID"})

    if not device.is_active:
        _raise(
            403,
            "This device has been deactivated by the pharmacy",
            {"reason": "DEVICE_INACTIVE"},
        )
    return device


async def _mint_token(
    db: AsyncSession, device: TemperatureDevice, session: TemperatureDeviceSession
) -> tuple[str, datetime]:
    """Issue a token for the session, revoking whatever it held before."""
    jti = uuid.uuid4().hex
    token, expires_at = create_device_token(
        temperature_device_id=device.temperature_device_id,
        medical_store_id=device.medical_store_id,
        session_id=session.session_id,
        jti=jti,
    )
    session.current_jti = jti
    session.token_issued_at = _now()
    session.token_expires_at = expires_at
    session.tokens_issued = (session.tokens_issued or 0) + 1
    device.last_seen_at = _now()
    return token, expires_at


async def start_logging(
    db: AsyncSession, device_secret: str
) -> tuple[TemperatureDevice, TemperatureDeviceSession, str, datetime, bool]:
    """Open a logging session (or resume the open one) and mint a token.

    Returns ``(device, session, token, expires_at, resumed)``.

    Calling this while a session is already open **resumes** it rather than
    opening a second one: a logger that reboots mid-run should continue the
    same run, and a device only ever has one session at a time. The previous
    token is revoked either way.
    """
    device = await resolve_device_by_secret(db, device_secret)

    session = await get_active_session(db, device.temperature_device_id)
    resumed = session is not None
    if session is None:
        session = TemperatureDeviceSession(
            temperature_device_id=device.temperature_device_id,
            medical_store_id=device.medical_store_id,
            status=TemperatureSessionStatus.ACTIVE.value,
            started_at=_now(),
        )
        db.add(session)
        # Needed before minting: the token embeds session_id.
        await db.flush()

    token, expires_at = await _mint_token(db, device, session)

    try:
        await db.commit()
        await db.refresh(session)
        await db.refresh(device)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to start temperature logging: {err}", err=str(exc))
        _raise(500, "Failed to start logging session")

    logger.info(
        "Temperature logging {verb} for device {id} (session {sid})",
        verb="resumed" if resumed else "started",
        id=device.temperature_device_id,
        sid=session.session_id,
    )
    return device, session, token, expires_at, resumed


async def issue_token(
    db: AsyncSession, device_secret: str
) -> tuple[TemperatureDevice, TemperatureDeviceSession, str, datetime]:
    """Re-authenticate an already-running session and mint a replacement token.

    This is the "my token expired" path. It deliberately refuses to open a
    session: if logging was stopped, the device should not silently resume —
    the caller gets a 409 telling it to start again.
    """
    device = await resolve_device_by_secret(db, device_secret)

    session = await get_active_session(db, device.temperature_device_id)
    if session is None:
        _raise(
            409,
            "No active logging session for this device. Call /temperature-devices/logging/start.",
            {"reason": "NO_ACTIVE_SESSION"},
        )

    token, expires_at = await _mint_token(db, device, session)
    try:
        await db.commit()
        await db.refresh(session)
        await db.refresh(device)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to renew temperature device token: {err}", err=str(exc))
        _raise(500, "Failed to issue device token")

    logger.info(
        "Renewed temperature device token for device {id} (session {sid})",
        id=device.temperature_device_id,
        sid=session.session_id,
    )
    return device, session, token, expires_at


async def stop_logging(
    db: AsyncSession, device: TemperatureDevice, *, reason: str
) -> TemperatureDeviceSession | None:
    """Close the open session and kill its token. Idempotent.

    Returns the closed session, or ``None`` when there was nothing running.
    """
    session = await get_active_session(db, device.temperature_device_id)
    if session is None:
        return None

    session.status = TemperatureSessionStatus.STOPPED.value
    session.ended_at = _now()
    session.end_reason = reason
    session.current_jti = None  # ← the live token stops being accepted
    device.last_seen_at = _now()

    try:
        await db.commit()
        await db.refresh(session)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to stop temperature logging: {err}", err=str(exc))
        _raise(500, "Failed to stop logging session")

    logger.info(
        "Temperature logging stopped for device {id} (session {sid}, reason={reason})",
        id=device.temperature_device_id,
        sid=session.session_id,
        reason=reason,
    )
    return session
