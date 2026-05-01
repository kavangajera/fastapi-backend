from datetime import datetime, timedelta
from email.message import EmailMessage
import secrets
import smtplib
import string

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.config import settings
from core.enums import OtpPurpose
from models.otp_code import OtpCode


def _raise_error(status_code: int, message: str):
    """Raise HTTPException with Response_Schema format in detail."""
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
    )


def _now() -> datetime:
    return datetime.utcnow()


def _generate_otp(length: int = 6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


def _send_email(to_email: str, subject: str, body: str):
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        _raise_error(500, "SMTP settings are not configured")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email
    message.set_content(body)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(message)


def _invalidate_existing_otps(
    db: Session,
    user_id: int,
    purpose: OtpPurpose,
    pharmacy_id: int | None,
    transfer_request_id: int | None,
    new_owner_id: int | None,
):
    query = db.query(OtpCode).filter(
        OtpCode.user_id == user_id,
        OtpCode.purpose == purpose,
        OtpCode.is_active.is_(True),
        OtpCode.used_at.is_(None),
    )
    if pharmacy_id is not None:
        query = query.filter(OtpCode.pharmacy_id == pharmacy_id)
    if transfer_request_id is not None:
        query = query.filter(OtpCode.transfer_request_id == transfer_request_id)
    if new_owner_id is not None:
        query = query.filter(OtpCode.new_owner_id == new_owner_id)

    try:
        query.update({OtpCode.is_active: False})
    except SQLAlchemyError:
        db.rollback()
        _raise_error(500, "Failed to invalidate existing OTPs")


def issue_otp(
    db: Session,
    user_id: int,
    email: str,
    purpose: OtpPurpose,
    pharmacy_id: int | None = None,
    transfer_request_id: int | None = None,
    new_owner_id: int | None = None,
):
    if not email:
        _raise_error(400, "User email is missing")

    expires_at = _now() + timedelta(seconds=settings.OTP_TTL_SECONDS)
    otp_code = _generate_otp()
    ph = PasswordHasher()

    _invalidate_existing_otps(
        db,
        user_id=user_id,
        purpose=purpose,
        pharmacy_id=pharmacy_id,
        transfer_request_id=transfer_request_id,
        new_owner_id=new_owner_id,
    )

    otp_record = OtpCode(
        user_id=user_id,
        purpose=purpose,
        code_hash=ph.hash(otp_code),
        attempts=0,
        max_attempts=settings.OTP_MAX_ATTEMPTS,
        expires_at=expires_at,
        is_active=True,
        pharmacy_id=pharmacy_id,
        transfer_request_id=transfer_request_id,
        new_owner_id=new_owner_id,
    )

    try:
        db.add(otp_record)
        db.commit()
        db.refresh(otp_record)
    except SQLAlchemyError:
        db.rollback()
        _raise_error(500, "Failed to store OTP")

    subject = "Queue RX OTP Verification"
    body = (
        f"Your verification code is {otp_code}. "
        f"It expires in {settings.OTP_TTL_SECONDS} seconds."
    )

    try:
        _send_email(email, subject, body)
    except (smtplib.SMTPException, OSError):
        try:
            otp_record.is_active = False
            db.commit()
        except SQLAlchemyError:
            db.rollback()
        _raise_error(500, "Failed to send OTP email")

    return otp_record


def verify_otp(
    db: Session,
    user_id: int,
    purpose: OtpPurpose,
    otp_code: str,
    pharmacy_id: int | None = None,
    transfer_request_id: int | None = None,
    new_owner_id: int | None = None,
):
    query = db.query(OtpCode).filter(
        OtpCode.user_id == user_id,
        OtpCode.purpose == purpose,
        OtpCode.is_active.is_(True),
        OtpCode.used_at.is_(None),
    )
    if pharmacy_id is not None:
        query = query.filter(OtpCode.pharmacy_id == pharmacy_id)
    if transfer_request_id is not None:
        query = query.filter(OtpCode.transfer_request_id == transfer_request_id)
    if new_owner_id is not None:
        query = query.filter(OtpCode.new_owner_id == new_owner_id)

    otp_record = query.order_by(OtpCode.created_at.desc()).first()
    if not otp_record:
        _raise_error(404, "OTP not found")

    now = _now()
    if otp_record.expires_at <= now:
        otp_record.is_active = False
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
        _raise_error(400, "OTP expired")

    if otp_record.attempts >= otp_record.max_attempts:
        otp_record.is_active = False
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
        _raise_error(400, "OTP attempts exceeded")

    ph = PasswordHasher()
    try:
        ph.verify(otp_record.code_hash, otp_code)
    except VerifyMismatchError:
        otp_record.attempts += 1
        if otp_record.attempts >= otp_record.max_attempts:
            otp_record.is_active = False
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            _raise_error(500, "Failed to update OTP attempts")
        _raise_error(400, "Invalid OTP")

    otp_record.used_at = now
    otp_record.is_active = False
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        _raise_error(500, "Failed to finalize OTP verification")

    return True
