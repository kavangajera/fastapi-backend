"""
services/password_reset_service.py
──────────────────────────────────
Forgot-password flow, in three steps:

1. ``POST /user/forgot-password``  — email → a 6-digit code is mailed.
2. ``POST /user/verify-reset-otp`` — email + code → short-lived reset token.
3. ``POST /user/reset-password``   — reset token + new password → done.

Why a token in the middle rather than posting the code alongside the new
password? The code stays valid for only as long as it takes to type it, the
new-password screen gets its own clock, and the code is never sent twice.

Security notes:

* Step 1 returns the **same response whether or not the account exists** —
  the endpoint cannot be used to enumerate registered emails.
* The reset token embeds a fingerprint of the current password hash, so it
  stops working the moment the password changes: it is effectively
  single-use even though it is stateless.
* A successful reset revokes every stored refresh token, logging the
  account out everywhere — a reset is the standard response to a suspected
  compromise, so old sessions must not survive it.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from fastapi import HTTPException
from jose import ExpiredSignatureError, JWTError, jwt
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.enums import OtpPurpose
from models.refresh_token import RefreshToken
from models.user import User
from schemas.password_reset_schemas import (
    ForgotPasswordInput,
    ResetPasswordInput,
    VerifyResetOtpInput,
)
from services import otp_service

_hasher = PasswordHasher()

_RESET_TOKEN_TYPE = "password_reset"

# Returned by step 1 regardless of whether the email is registered.
_GENERIC_SENT_MESSAGE = (
    "If an account exists for that email address, a verification code has been sent to it."
)


def _raise_error(status_code: int, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
    )


def _password_fingerprint(password_hash: str) -> str:
    """Short digest of the stored hash — binds a reset token to one password."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def _create_reset_token(user: User) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "user_id": user.user_id,
        "typ": _RESET_TOKEN_TYPE,
        "pwd": _password_fingerprint(user.password_hash),
        # Standard `exp` claim (not this codebase's custom `expire`) so the
        # JWT library enforces expiry for us.
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _decode_reset_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except ExpiredSignatureError:
        _raise_error(400, "Reset session has expired. Please start over.")
    except JWTError:
        _raise_error(400, "Invalid reset token. Please start over.")

    if payload.get("typ") != _RESET_TOKEN_TYPE:
        _raise_error(400, "Invalid reset token. Please start over.")
    return payload


async def _get_active_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or user.IsActive != 1:
        return None
    return user


# ================= STEP 1 — request a code =================


async def request_password_reset(payload: ForgotPasswordInput, db: AsyncSession) -> dict:
    email = payload.user_email.strip().lower()
    user = await _get_active_user_by_email(db, email)

    if user is None:
        # Deliberately indistinguishable from the success path.
        logger.info("Password reset requested for unknown/inactive email: {email}", email=email)
        return {"email_sent": True, "message": _GENERIC_SENT_MESSAGE}

    await otp_service.issue_otp(
        db,
        user_id=user.user_id,
        email=user.email,
        purpose=OtpPurpose.PASSWORD_RESET,
        purpose_line=(
            "We received a request to reset the password for your Queue RX account."
        ),
        ttl_seconds=settings.PASSWORD_RESET_OTP_TTL_SECONDS,
    )

    return {"email_sent": True, "message": _GENERIC_SENT_MESSAGE}


# ================= STEP 2 — verify the code =================


async def verify_password_reset_otp(payload: VerifyResetOtpInput, db: AsyncSession) -> dict:
    email = payload.user_email.strip().lower()
    user = await _get_active_user_by_email(db, email)

    if user is None:
        # Same wording the OTP service uses for a missing code, so a wrong
        # email is not distinguishable from a wrong code.
        _raise_error(404, "No active verification code found. Please request a new one.")

    await otp_service.verify_otp(
        db,
        user_id=user.user_id,
        purpose=OtpPurpose.PASSWORD_RESET,
        code=payload.otp_code,
        consume=True,
    )

    return {
        "reset_token": _create_reset_token(user),
        "expires_in_minutes": settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
    }


# ================= STEP 3 — set the new password =================


async def reset_password(payload: ResetPasswordInput, db: AsyncSession) -> dict:
    claims = _decode_reset_token(payload.reset_token)

    result = await db.execute(select(User).where(User.user_id == claims["user_id"]))
    user = result.scalar_one_or_none()
    if user is None or user.IsActive != 1:
        _raise_error(404, "Account not found")

    # The token was minted against a specific password hash. If that hash has
    # changed, the token has already been spent (or the password was changed
    # by other means) and must not work again.
    if claims.get("pwd") != _password_fingerprint(user.password_hash):
        _raise_error(400, "This reset link has already been used. Please start over.")

    try:
        _hasher.verify(user.password_hash, payload.new_password)
        _raise_error(400, "New password must be different from your current password")
    except HTTPException:
        raise
    except Exception:
        # Mismatch (the expected case) — the new password is genuinely new.
        pass

    try:
        user.password_hash = _hasher.hash(payload.new_password)
        # A password reset ends every existing session.
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.user_id, RefreshToken.revoked.is_(False))
            .values(revoked=True)
        )
        user.IsLogout = 1
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Database error resetting password: {err}", err=str(exc))
        _raise_error(500, "Failed to reset password")

    # Retire any codes still outstanding for this account.
    await otp_service.invalidate_all(
        db, user_id=user.user_id, purpose=OtpPurpose.PASSWORD_RESET
    )

    logger.info("Password reset completed for user_id={uid}", uid=user.user_id)
    return {
        "user_id": user.user_id,
        "email": user.email,
        "message": "Password reset successfully. Please log in with your new password.",
    }
