"""
services/email_service.py
─────────────────────────
The single outbound-email surface for the whole app.

`smtplib` is blocking, and every caller here lives on the async request
path, so the actual send runs in a worker thread via `asyncio.to_thread`
— the event loop (and Kafka heartbeats, in worker processes) stays free.

Configuration lives in `core/config.py`. In practice only two `.env` keys
are needed::

    SMTP_USERNAME=you@gmail.com
    SMTP_PASSWORD=abcdefghijklmnop      # Google App Password, no spaces

If `SMTP_USERNAME` is blank the service degrades to **log-only** mode: the
message (OTP included) is written to the log instead of being sent, so the
whole flow stays testable before credentials exist. It never raises in that
mode — check the logs for the code.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from fastapi import HTTPException
from loguru import logger

from core.config import settings


def _raise_error(status_code: int, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
    )


def is_configured() -> bool:
    """True when real SMTP credentials are present."""
    return bool(settings.SMTP_HOST and settings.SMTP_USERNAME and settings.SMTP_PASSWORD)


def _from_address() -> str:
    email = settings.SMTP_FROM_EMAIL or settings.SMTP_USERNAME
    return formataddr((settings.SMTP_FROM_NAME, email)) if settings.SMTP_FROM_NAME else email


def _build_message(to_email: str, subject: str, body: str, html: str | None) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _from_address()
    message["To"] = to_email
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def _send_sync(message: EmailMessage) -> None:
    """Blocking SMTP send. Always called through `asyncio.to_thread`."""
    context = ssl.create_default_context()

    if settings.SMTP_USE_SSL:
        server = smtplib.SMTP_SSL(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
            context=context,
        )
    else:
        server = smtplib.SMTP(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
        )

    with server:
        server.ehlo()
        if settings.SMTP_USE_TLS and not settings.SMTP_USE_SSL:
            server.starttls(context=context)
            server.ehlo()
        if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(message)


async def send_email(
    to_email: str,
    subject: str,
    body: str,
    html: str | None = None,
    *,
    raise_on_failure: bool = True,
) -> bool:
    """Send one email. Returns True if it was actually handed to the SMTP server.

    In log-only mode (no credentials, or ``SMTP_DEBUG_LOG_ONLY=true``) the
    message is logged and ``False`` is returned without raising — callers
    treat that as a soft success so local development is not blocked.

    With ``raise_on_failure=False`` a genuine SMTP error is swallowed and
    logged; use it for advisory mail (notifications) where the surrounding
    operation must still succeed. Leave it True for mail that carries a
    secret the user cannot proceed without (OTPs).
    """
    if not to_email:
        _raise_error(400, "Recipient email address is missing")

    if settings.SMTP_DEBUG_LOG_ONLY or not is_configured():
        logger.warning(
            "SMTP not configured — email NOT sent (log-only mode).\n"
            "  To: {to}\n  Subject: {subject}\n{body}",
            to=to_email,
            subject=subject,
            body=body,
        )
        return False

    message = _build_message(to_email, subject, body, html)
    try:
        await asyncio.to_thread(_send_sync, message)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        logger.error("Failed to send email to {to}: {err}", to=to_email, err=str(exc))
        if raise_on_failure:
            _raise_error(500, "Failed to send email. Please try again later.")
        return False

    logger.info("Email sent to {to} — {subject}", to=to_email, subject=subject)
    return True


# ─────────────────────────────────────────────────────────────────────
# Templates
# ─────────────────────────────────────────────────────────────────────
# Kept here (not in the services that trigger them) so wording and markup
# stay consistent across every transactional email we send.

_HTML_SHELL = """\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
            max-width:520px;margin:0 auto;padding:24px;color:#1f2933;">
  <h2 style="margin:0 0 16px;font-size:20px;color:#0b3d91;">{heading}</h2>
  {content}
  <hr style="border:none;border-top:1px solid #e4e7eb;margin:24px 0 12px;">
  <p style="font-size:12px;color:#7b8794;margin:0;">
    This is an automated message from Queue RX. Please do not reply.
  </p>
</div>"""

_CODE_BLOCK = """\
<p style="font-size:32px;letter-spacing:8px;font-weight:700;
          background:#f5f7fa;border-radius:8px;padding:16px;text-align:center;
          margin:16px 0;">{code}</p>"""


def otp_email(code: str, purpose_line: str, ttl_minutes: int) -> tuple[str, str]:
    """Build (plain_text, html) for a one-time-code email."""
    text = (
        f"{purpose_line}\n\n"
        f"Your verification code is: {code}\n\n"
        f"It expires in {ttl_minutes} minute(s). If you did not request this, "
        f"you can safely ignore this email — no change has been made.\n"
    )
    html = _HTML_SHELL.format(
        heading="Your verification code",
        content=(
            f"<p style='margin:0;font-size:14px;'>{purpose_line}</p>"
            + _CODE_BLOCK.format(code=code)
            + f"<p style='font-size:13px;color:#52606d;margin:0;'>This code expires in "
            f"<strong>{ttl_minutes} minute(s)</strong>. If you did not request it, "
            f"ignore this email — nothing has changed.</p>"
        ),
    )
    return text, html


def transfer_request_email(
    pharmacy_name: str,
    current_owner_name: str,
    current_owner_email: str,
    expires_at_str: str,
) -> tuple[str, str]:
    """Notification mailed to the *prospective* new owner when a transfer opens."""
    text = (
        f"{current_owner_name} ({current_owner_email}) has requested to transfer "
        f"ownership of the pharmacy \"{pharmacy_name}\" to you on Queue RX.\n\n"
        f"Open Queue RX and go to Ownership Transfers to accept or decline. "
        f"Accepting requires a verification code sent to this address.\n\n"
        f"This request expires on {expires_at_str} UTC.\n\n"
        f"If you were not expecting this, decline the request.\n"
    )
    html = _HTML_SHELL.format(
        heading="You have been offered pharmacy ownership",
        content=(
            f"<p style='margin:0 0 12px;font-size:14px;'><strong>{current_owner_name}</strong> "
            f"({current_owner_email}) has requested to transfer ownership of "
            f"<strong>{pharmacy_name}</strong> to you.</p>"
            f"<p style='margin:0 0 12px;font-size:14px;'>Open Queue RX and go to "
            f"<strong>Ownership Transfers</strong> to accept or decline. Accepting "
            f"requires a verification code sent to this address.</p>"
            f"<p style='font-size:13px;color:#52606d;margin:0;'>This request expires on "
            f"<strong>{expires_at_str} UTC</strong>. If you were not expecting it, decline it.</p>"
        ),
    )
    return text, html


def transfer_outcome_email(
    pharmacy_name: str,
    new_owner_name: str,
    accepted: bool,
) -> tuple[str, str]:
    """Result notification mailed back to the previous owner."""
    verb = "accepted" if accepted else "declined"
    tail = (
        "You no longer have owner access to this pharmacy."
        if accepted
        else "You remain the owner of this pharmacy."
    )
    text = (
        f"{new_owner_name} has {verb} your request to transfer ownership of "
        f"\"{pharmacy_name}\".\n\n{tail}\n"
    )
    html = _HTML_SHELL.format(
        heading=f"Ownership transfer {verb}",
        content=(
            f"<p style='margin:0 0 12px;font-size:14px;'><strong>{new_owner_name}</strong> has "
            f"<strong>{verb}</strong> your request to transfer ownership of "
            f"<strong>{pharmacy_name}</strong>.</p>"
            f"<p style='font-size:13px;color:#52606d;margin:0;'>{tail}</p>"
        ),
    )
    return text, html
