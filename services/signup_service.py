"""
services/signup_service.py
──────────────────────────
Registration, gated on proof that the applicant controls the email address.

Three endpoints, two of which do not create anything:

1. ``POST /user/signup``            — email + password → a 6-digit code is mailed.
2. ``POST /user/verify-signup-otp`` — email + code → **the account is created here**.
3. ``POST /user/resend-signup-otp`` — mail a fresh code for a signup in progress.

Why the credentials are staged rather than written as a disabled `user`
row: an unverified row in `user` would occupy the unique email address,
letting anyone squat an address they do not own, and every read path
(login, admin listings, technician lookups) would have to remember to
exclude it. A separate `pending_signup` table cannot log in by
construction — there is no flag to get wrong.

Security properties:

* **No path creates a `user` row without a redeemed code.** `user_service`
  exposes only `create_verified_user`, and this module is its sole caller.
* The password is Argon2id-hashed the moment it arrives and is never held
  in the clear, not even while pending.
* The code is hashed the same way. A dump of `pending_signup` yields
  neither the password nor a usable code.
* Wrong guesses are counted and the staged signup dies at
  ``SIGNUP_OTP_MAX_ATTEMPTS``; the code also expires on its own clock.
* Requesting a new code invalidates the previous one — only the most
  recently mailed code is ever live.
* Everything is metered **per email address**, never per caller IP: mail
  volume by the cooldown and total-send caps on the staged row, request
  volume by the limiter in `core/rate_limit.py`. Two people signing up
  from the same pharmacy or the same carrier NAT therefore never consume
  each other's budget.

Note on 409: this flow answers "that email is already registered"
explicitly, which is a deliberate product decision for signup UX. It does
mean the endpoint can confirm whether a given address has an account.
Per-email metering bounds how hard any one address can be probed, but it
cannot see a caller walking a list of addresses — that is a job for an
edge limiter (nginx / Cloudflare), not this process.
`POST /user/forgot-password` still answers generically, so the two flows
do not cancel each other out.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException
from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core import rate_limit
from core.config import settings
from models.pending_signup import PendingSignup
from models.user import User
from schemas.signup_input_user_schema import Signup_Input_User_Schema
from schemas.signup_otp_schemas import ResendSignupOtpInput, VerifySignupOtpInput
from services import email_service, user_service

_hasher = PasswordHasher()

_PURPOSE_LINE = (
    "Use this code to finish creating your Queue RX account. "
    "The account is not created until the code is entered."
)

_DEFAULT_CONTACT_NUMBER = "1234567890"


def _raise_error(status_code: int, message: str, *, retry_after: int | None = None):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
        # Gives the client something to act on rather than guess at.
        headers={"Retry-After": str(retry_after)} if retry_after else None,
    )


def _now() -> datetime:
    # Naive UTC, matching the convention used across the codebase.
    return datetime.utcnow()


def _generate_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(settings.OTP_LENGTH))


def _ttl_minutes() -> int:
    return max(1, round(settings.SIGNUP_OTP_TTL_SECONDS / 60))


# Two independent per-email buckets. Mail-sending calls (step 1, resend) are
# the ones worth holding down; redeeming a code is already bounded by the
# staged row's own attempt budget, so it gets its own allowance — otherwise
# a handful of mistyped codes would lock the applicant out of the endpoint
# that finishes their signup.
_SCOPE_SEND = "signup-send"
_SCOPE_VERIFY = "signup-verify"


def _throttle(email: str, scope: str, *, multiplier: int = 1) -> None:
    """Per-email budget on the unauthenticated signup endpoints.

    Keyed on the address being signed up, so one applicant's retries can
    never exhaust another's allowance — the two share a NAT, not a bucket.
    """
    rate_limit.enforce(
        rate_limit.subject_key(email, scope),
        limit=settings.SIGNUP_RATE_LIMIT_PER_EMAIL * multiplier,
        window_seconds=settings.SIGNUP_RATE_LIMIT_WINDOW_SECONDS,
        message="Too many signup requests for this email.",
    )


async def _commit(db: AsyncSession, what: str) -> None:
    try:
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Database error during {what}: {err}", what=what, err=str(exc))
        _raise_error(500, "Something went wrong. Please try again.")


async def _email_is_taken(db: AsyncSession, email: str) -> bool:
    result = await db.execute(select(User.user_id).where(User.email == email))
    return result.scalar_one_or_none() is not None


async def _purge_expired(db: AsyncSession) -> None:
    """Drop staged signups nobody came back for.

    Opportunistic — cheap, bounded, and it keeps the table from growing
    without needing a scheduled job.
    """
    try:
        await db.execute(delete(PendingSignup).where(PendingSignup.expires_at <= _now()))
    except SQLAlchemyError as exc:
        # Housekeeping only — never fail the caller's request over it.
        await db.rollback()
        logger.warning("Could not purge expired pending signups: {err}", err=str(exc))


async def _get_pending(db: AsyncSession, email: str) -> PendingSignup | None:
    result = await db.execute(select(PendingSignup).where(PendingSignup.email == email))
    return result.scalar_one_or_none()


async def _mail_code(db: AsyncSession, pending: PendingSignup, code: str) -> None:
    """Send the code; on failure discard the staged signup and raise.

    Discarding rather than keeping the row is what stops a failed send from
    leaving the applicant behind a cooldown for a code that never arrived.
    """
    text, html = email_service.otp_email(code, _PURPOSE_LINE, _ttl_minutes())
    try:
        await email_service.send_email(
            pending.email, "Queue RX verification code", text, html=html
        )
    except HTTPException:
        try:
            await db.delete(pending)
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
        raise


def _stage(pending: PendingSignup, *, code: str, first_send: bool) -> None:
    """Point a pending row at a freshly minted code.

    Resetting `attempts` matters: the new code must not inherit the failed
    guesses of the old one, and the old hash is overwritten here, so the
    previous code stops working the moment this row is saved.
    """
    now = _now()
    pending.code_hash = _hasher.hash(code)
    pending.attempts = 0
    pending.max_attempts = settings.SIGNUP_OTP_MAX_ATTEMPTS
    pending.expires_at = now + timedelta(seconds=settings.SIGNUP_OTP_TTL_SECONDS)
    pending.send_count = 1 if first_send else pending.send_count + 1
    pending.last_sent_at = now


def _enforce_send_budget(pending: PendingSignup) -> None:
    """Cooldown + total-sends cap, so one address cannot be mail-bombed."""
    elapsed = (_now() - pending.last_sent_at).total_seconds()
    cooldown = settings.SIGNUP_OTP_RESEND_COOLDOWN_SECONDS
    if elapsed < cooldown:
        wait = max(1, int(cooldown - elapsed))
        _raise_error(
            429,
            f"A code was just sent. Please wait {wait}s before requesting another.",
            retry_after=wait,
        )

    if pending.send_count >= settings.SIGNUP_OTP_MAX_SENDS:
        # The address frees up when the staged signup expires.
        wait = max(1, int((pending.expires_at - _now()).total_seconds()))
        _raise_error(
            429,
            "Too many codes requested for this email. "
            f"Please wait {_ttl_minutes()} minutes and start over.",
            retry_after=wait,
        )


def _sent_response(email: str) -> dict:
    return {
        "email_sent": True,
        "user_email": email,
        "expires_in_minutes": _ttl_minutes(),
        "message": (
            f"A verification code has been sent to {email}. "
            "Enter it to finish creating your account."
        ),
    }


# ================= STEP 1 — stage the signup, mail a code =================


async def request_signup_otp(
    payload: Signup_Input_User_Schema,
    db: AsyncSession,
) -> dict:
    email = payload.user_email
    _throttle(email, _SCOPE_SEND)

    await _purge_expired(db)

    if await _email_is_taken(db, email):
        _raise_error(
            409,
            "An account with this email already exists. "
            "Please log in, or use Forgot Password if you cannot get in.",
        )

    pending = await _get_pending(db, email)
    code = _generate_code()

    if pending is None:
        pending = PendingSignup(
            email=email,
            username=email.split("@")[0][:100],
            contact_number=_DEFAULT_CONTACT_NUMBER,
            password_hash=_hasher.hash(payload.input_password),
            device_id=payload.device_id,
        )
        _stage(pending, code=code, first_send=True)
        db.add(pending)
    else:
        # A second step-1 for the same address is a legitimate "I mistyped
        # my password" retry, so the staged credentials are replaced — but
        # the send budget still applies, and it is the *new* code that
        # becomes live.
        _enforce_send_budget(pending)
        pending.password_hash = _hasher.hash(payload.input_password)
        pending.username = email.split("@")[0][:100]
        if payload.device_id:
            pending.device_id = payload.device_id
        _stage(pending, code=code, first_send=False)

    try:
        await db.commit()
    except IntegrityError:
        # Two concurrent step-1s for the same address; the loser retries.
        await db.rollback()
        _raise_error(409, "A signup for this email is already in progress. Please try again.")
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Database error staging signup: {err}", err=str(exc))
        _raise_error(500, "Something went wrong. Please try again.")

    await _mail_code(db, pending, code)
    logger.info("Signup verification code issued for {email}", email=email)
    return _sent_response(email)


# ================= RESEND — new code, same staged signup =================


async def resend_signup_otp(
    payload: ResendSignupOtpInput,
    db: AsyncSession,
) -> dict:
    email = payload.user_email
    _throttle(email, _SCOPE_SEND)

    pending = await _get_pending(db, email)

    if pending is None or pending.expires_at <= _now():
        if pending is not None:
            await db.delete(pending)
            await _commit(db, "signup resend cleanup")
        _raise_error(
            404,
            "No signup is awaiting verification for this email. Please start signup again.",
        )

    _enforce_send_budget(pending)

    code = _generate_code()
    _stage(pending, code=code, first_send=False)
    await _commit(db, "signup code resend")

    await _mail_code(db, pending, code)
    logger.info("Signup verification code re-sent for {email}", email=email)
    return _sent_response(email)


# ================= STEP 2 — redeem the code, create the account =================


async def verify_signup_otp(
    payload: VerifySignupOtpInput,
    db: AsyncSession,
) -> dict:
    email = payload.user_email
    _throttle(email, _SCOPE_VERIFY, multiplier=3)

    pending = await _get_pending(db, email)

    if pending is None:
        _raise_error(
            404,
            "No signup is awaiting verification for this email. Please start signup again.",
        )

    async def _discard(message: str):
        await db.delete(pending)
        await _commit(db, "discarding staged signup")
        _raise_error(400, message)

    if pending.expires_at <= _now():
        await _discard("Verification code has expired. Please start signup again.")

    if pending.attempts >= pending.max_attempts:
        await _discard("Too many incorrect attempts. Please start signup again.")

    try:
        _hasher.verify(pending.code_hash, payload.otp_code.strip())
    except VerifyMismatchError:
        pending.attempts += 1
        remaining = pending.max_attempts - pending.attempts
        if remaining <= 0:
            await _discard("Too many incorrect attempts. Please start signup again.")
        await _commit(db, "recording failed signup code attempt")
        _raise_error(400, f"Invalid verification code. {remaining} attempt(s) remaining.")

    # Re-checked here, not just at step 1: the address may have been claimed
    # in the meantime (another signup, or an admin-created account).
    if await _email_is_taken(db, email):
        await db.delete(pending)
        await _commit(db, "discarding staged signup for taken email")
        _raise_error(409, "An account with this email already exists. Please log in.")

    user_model = await user_service.create_verified_user(
        db,
        username=pending.username,
        email=pending.email,
        contact_number=pending.contact_number,
        password_hash=pending.password_hash,
        device_id=payload.device_id or pending.device_id,
    )

    # The account and the consumption of the code land in one transaction —
    # a created user can never coexist with a still-redeemable code.
    await db.delete(pending)
    try:
        await db.commit()
        await db.refresh(user_model)
    except IntegrityError:
        await db.rollback()
        _raise_error(409, "An account with this email already exists. Please log in.")
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Database error creating verified user: {err}", err=str(exc))
        _raise_error(500, "Something went wrong while creating your account.")

    logger.info(
        "Account created after email verification: user_id={uid} email={email}",
        uid=user_model.user_id,
        email=email,
    )
    return user_service.to_user_output(user_model)
