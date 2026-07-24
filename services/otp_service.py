"""
services/otp_service.py
───────────────────────
Issue + verify one-time codes. Shared by password reset and pharmacy
ownership transfer.

Guarantees:

* Codes are stored **hashed** (Argon2id) — a DB dump leaks nothing usable.
* Issuing a code **invalidates any earlier live code** for the same
  (user, purpose, scope), so only one code is ever valid at a time.
* Verification is scoped: a code is only accepted for the exact purpose and
  scope it was issued under.
* Wrong guesses are counted; the code dies once `max_attempts` is reached.
* Consumed codes are marked `used_at` and deactivated — never replayable.

Email delivery is fire-and-forget from the caller's perspective but is
awaited here: if the mail cannot be sent we deactivate the code and raise,
rather than leaving the user waiting for a code that never arrives.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.enums import OtpPurpose
from models.otp_code import OtpCode
from services import email_service

_hasher = PasswordHasher()


def _raise_error(status_code: int, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
    )


def _now() -> datetime:
    # Naive UTC, matching the convention used across the codebase.
    return datetime.utcnow()


def _generate_code(length: int | None = None) -> str:
    length = length or settings.OTP_LENGTH
    return "".join(secrets.choice("0123456789") for _ in range(length))


def _scope_filters(stmt, medical_store_id, transfer_id, new_owner_id):
    """Apply scope predicates, matching NULL against NULL.

    Always constraining every scope column (rather than only the ones the
    caller passed) is what stops a broadly-scoped code from satisfying a
    narrowly-scoped check.
    """
    return stmt.where(
        OtpCode.medical_store_id.is_(None)
        if medical_store_id is None
        else OtpCode.medical_store_id == medical_store_id,
        OtpCode.transfer_id.is_(None)
        if transfer_id is None
        else OtpCode.transfer_id == transfer_id,
        OtpCode.new_owner_id.is_(None)
        if new_owner_id is None
        else OtpCode.new_owner_id == new_owner_id,
    )


async def issue_otp(
    db: AsyncSession,
    *,
    user_id: int,
    email: str,
    purpose: OtpPurpose,
    purpose_line: str,
    ttl_seconds: int | None = None,
    medical_store_id: int | None = None,
    transfer_id: int | None = None,
    new_owner_id: int | None = None,
) -> OtpCode:
    """Generate, store and email a fresh code. Returns the stored row."""
    if not email:
        _raise_error(400, "User email is missing")

    ttl = ttl_seconds or settings.OTP_TTL_SECONDS
    code = _generate_code()

    try:
        # Kill any previously live code for this exact scope.
        await db.execute(
            _scope_filters(
                update(OtpCode).where(
                    OtpCode.user_id == user_id,
                    OtpCode.purpose == purpose.value,
                    OtpCode.is_active.is_(True),
                    OtpCode.used_at.is_(None),
                ),
                medical_store_id,
                transfer_id,
                new_owner_id,
            ).values(is_active=False)
        )

        otp_row = OtpCode(
            user_id=user_id,
            purpose=purpose.value,
            code_hash=_hasher.hash(code),
            attempts=0,
            max_attempts=settings.OTP_MAX_ATTEMPTS,
            expires_at=_now() + timedelta(seconds=ttl),
            is_active=True,
            medical_store_id=medical_store_id,
            transfer_id=transfer_id,
            new_owner_id=new_owner_id,
        )
        db.add(otp_row)
        await db.commit()
        await db.refresh(otp_row)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Database error issuing OTP: {err}", err=str(exc))
        _raise_error(500, "Failed to issue verification code")

    ttl_minutes = max(1, round(ttl / 60))
    text, html = email_service.otp_email(code, purpose_line, ttl_minutes)

    try:
        await email_service.send_email(
            email, "Queue RX verification code", text, html=html
        )
    except HTTPException:
        # Mail failed — retire the code so a later retry issues a clean one.
        otp_row.is_active = False
        try:
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
        raise

    return otp_row


async def verify_otp(
    db: AsyncSession,
    *,
    user_id: int,
    purpose: OtpPurpose,
    code: str,
    medical_store_id: int | None = None,
    transfer_id: int | None = None,
    new_owner_id: int | None = None,
    consume: bool = True,
) -> OtpCode:
    """Validate `code`. Raises 400/404 on any failure; returns the row on success.

    With ``consume=False`` a correct code stays usable (attempts are still
    counted on failure) — for flows that check the code before the final,
    separate submit.
    """
    if not code or not code.strip():
        _raise_error(400, "Verification code is required")
    code = code.strip()

    stmt = _scope_filters(
        select(OtpCode).where(
            OtpCode.user_id == user_id,
            OtpCode.purpose == purpose.value,
            OtpCode.is_active.is_(True),
            OtpCode.used_at.is_(None),
        ),
        medical_store_id,
        transfer_id,
        new_owner_id,
    ).order_by(OtpCode.otp_id.desc())

    otp_row = (await db.execute(stmt)).scalars().first()
    if not otp_row:
        _raise_error(404, "No active verification code found. Please request a new one.")

    async def _save() -> None:
        try:
            await db.commit()
        except SQLAlchemyError as exc:
            await db.rollback()
            logger.error("Database error updating OTP: {err}", err=str(exc))
            _raise_error(500, "Failed to process verification code")

    if otp_row.expires_at <= _now():
        otp_row.is_active = False
        await _save()
        _raise_error(400, "Verification code has expired. Please request a new one.")

    if otp_row.attempts >= otp_row.max_attempts:
        otp_row.is_active = False
        await _save()
        _raise_error(400, "Too many incorrect attempts. Please request a new code.")

    try:
        _hasher.verify(otp_row.code_hash, code)
    except VerifyMismatchError:
        otp_row.attempts += 1
        remaining = otp_row.max_attempts - otp_row.attempts
        if remaining <= 0:
            otp_row.is_active = False
        await _save()
        if remaining <= 0:
            _raise_error(400, "Too many incorrect attempts. Please request a new code.")
        _raise_error(400, f"Invalid verification code. {remaining} attempt(s) remaining.")

    if consume:
        otp_row.used_at = _now()
        otp_row.is_active = False
        await _save()

    return otp_row


async def invalidate_all(
    db: AsyncSession,
    *,
    user_id: int,
    purpose: OtpPurpose,
) -> None:
    """Retire every live code of `purpose` for a user (any scope).

    Called after a password change so codes minted before the change cannot
    still be redeemed.
    """
    try:
        await db.execute(
            update(OtpCode)
            .where(
                OtpCode.user_id == user_id,
                OtpCode.purpose == purpose.value,
                OtpCode.is_active.is_(True),
            )
            .values(is_active=False)
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Database error invalidating OTPs: {err}", err=str(exc))
