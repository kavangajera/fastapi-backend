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

Two more are optional but worth setting — both feed the footer/headers
that make the mail read as a real business's transactional email:

    SMTP_REPLY_TO=support@yourpharmacy.com
    EMAIL_SENDER_IDENTITY=Queue RX, <city> · support@yourpharmacy.com

If `SMTP_USERNAME` is blank the service degrades to **log-only** mode: the
message (OTP included) is written to the log instead of being sent, so the
whole flow stays testable before credentials exist. It never raises in that
mode — check the logs for the code.

Deliverability
──────────────
The headers in `_build_message` and the wording rules in the template
section below are the part of "don't land in spam" that code controls.
They are the smaller part. What actually decides it:

1. **Authentication.** `From:` must be a domain the sending account can
   sign for. Sending as `noreply@yourpharmacy.com` through a Gmail
   account authenticates as gmail.com, DMARC fails to align, and the mail
   is filtered no matter how the body reads. Either send From the Gmail
   address itself, or add the address as a verified alias in Gmail.
   `_check_from_alignment` logs a warning when the two disagree.
2. **Domain reputation.** A brand-new domain has none. Volume ramps
   slowly; sudden bursts to cold addresses look like a list purchase.
3. **A real DNS setup** on your own domain: SPF (`v=spf1 include:...
   -all`), DKIM (published by the provider), and DMARC
   (`v=DMARC1; p=none; rua=mailto:...` to start, tightened once the
   reports are clean).

For anything beyond low volume, a transactional provider (SES, Postmark,
Resend, SendGrid) handles 1–3 for you and gives bounce/complaint
feedback Gmail SMTP does not. Only `_send_sync` would change — swap the
SMTP host/credentials, or the whole function for their API client; every
caller goes through `send_email` and stays untouched.
"""

from __future__ import annotations

import asyncio
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from html import escape

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


def _from_email() -> str:
    return settings.SMTP_FROM_EMAIL or settings.SMTP_USERNAME


def _from_address() -> str:
    email = _from_email()
    return formataddr((settings.SMTP_FROM_NAME, email)) if settings.SMTP_FROM_NAME else email


def _check_from_alignment() -> None:
    """Warn when the From domain cannot be DKIM-aligned with the sender.

    The single biggest reason these emails land in spam is not their
    wording — it is `From:` claiming a domain the authenticated account
    cannot sign for. Gmail will happily relay it, DKIM will align to
    gmail.com instead, DMARC evaluation fails, and the message is filtered.
    Logged once per send attempt rather than raised, because the mail is
    still worth trying.
    """
    from_domain = _from_email().rsplit("@", 1)[-1].lower()
    auth_domain = settings.SMTP_USERNAME.rsplit("@", 1)[-1].lower()
    if from_domain and auth_domain and from_domain != auth_domain:
        logger.warning(
            "SMTP_FROM_EMAIL domain ({f}) differs from the authenticated account "
            "({a}) — unless {f} is a verified alias, DKIM/DMARC will not align and "
            "delivery to spam is likely.",
            f=from_domain,
            a=auth_domain,
        )


def _build_message(to_email: str, subject: str, body: str, html: str | None) -> EmailMessage:
    """Assemble a message with the headers receivers expect from real mail.

    Each header earns its place:

    * `Date` / `Message-ID` — absent or malformed, both are strong spam
      signals. `make_msgid` is given the From domain explicitly; left to
      itself it stamps the sending machine's hostname, which on a dev box
      or container is meaningless and looks forged.
    * `Reply-To` — a monitored address. "Do not reply" with nowhere to
      reply to reads as bulk mail.
    * `Auto-Submitted` — RFC 3834. Marks this as transactional and stops
      out-of-office autoresponders bouncing back at us.
    * `X-Entity-Ref-ID` — unique per message so Gmail does not collapse
      consecutive codes into one thread, hiding the newest behind the
      oldest.

    Deliberately **not** set: `List-Unsubscribe` and `Precedence: bulk`.
    Both announce bulk mail; a security code is transactional, the
    recipient asked for it seconds ago, and there is nothing to
    unsubscribe from.
    """
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _from_address()
    message["To"] = to_email
    message["Date"] = formatdate(localtime=True)

    domain = _from_email().rsplit("@", 1)[-1] or None
    message["Message-ID"] = make_msgid(domain=domain)

    reply_to = settings.SMTP_REPLY_TO or _from_email()
    if reply_to:
        message["Reply-To"] = reply_to

    message["Auto-Submitted"] = "auto-generated"
    message["X-Entity-Ref-ID"] = secrets.token_hex(12)

    # Plain text first, HTML as the alternative — the order defines which
    # part is the fallback. A text part that says the same thing as the
    # HTML also matters: filters compare them, and an empty or mismatched
    # text part is treated as an attempt to hide the real content.
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

    _check_from_alignment()
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
#
# Wording and markup rules these templates follow, all of them things
# filters actually score:
#
#   * The plain-text part says the same thing as the HTML part. A stub
#     text part ("view this in HTML") next to a rich HTML part is read as
#     hiding the real content.
#   * A complete HTML document — doctype, <head>, charset — not a bare
#     <div> fragment.
#   * No images, no tracking pixel, no link shorteners, and for the OTP
#     mail no links at all: nothing for a filter to resolve and distrust.
#     A link-free security email also trains users not to click links in
#     one, which is the correct habit.
#   * No urgency punctuation, no ALL CAPS, no "act now" / "verify your
#     account or else" phrasing — the phishing register is exactly what
#     spam models are tuned on, and a real OTP mail that imitates it gets
#     filtered alongside the fakes.
#   * A named, identifiable sender in the footer.
#
# Everything interpolated into the HTML is escaped: pharmacy and person
# names come from user input, and an unescaped `<` in a name would break
# the markup at best and inject content at worst.


def _shell(heading: str, preheader: str, content: str, footer: str) -> str:
    """Wrap body content in the shared HTML document.

    `preheader` is the grey snippet inboxes show after the subject. Left
    unset, clients scrape the first visible text instead, which for a code
    email means the inbox preview leaks the code itself.
    """
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{escape(heading)}</title>
</head>
<body style="margin:0;padding:0;background:#f5f7fa;">
<span style="display:none;visibility:hidden;opacity:0;height:0;width:0;
             max-height:0;max-width:0;overflow:hidden;mso-hide:all;">{escape(preheader)}</span>
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
            max-width:520px;margin:0 auto;padding:24px;color:#1f2933;background:#ffffff;">
  <p style="margin:0 0 20px;font-size:15px;font-weight:600;color:#0b3d91;
            letter-spacing:0.3px;">Queue RX</p>
  <h2 style="margin:0 0 16px;font-size:20px;color:#1f2933;">{escape(heading)}</h2>
  {content}
  <hr style="border:none;border-top:1px solid #e4e7eb;margin:24px 0 12px;">
  <p style="font-size:12px;color:#7b8794;margin:0 0 6px;">{escape(footer)}</p>
  <p style="font-size:12px;color:#7b8794;margin:0;">
    {escape(settings.EMAIL_SENDER_IDENTITY)} &middot; sent automatically, replies are not monitored.
  </p>
</div>
</body>
</html>"""


_CODE_BLOCK = """\
<p style="font-size:32px;letter-spacing:8px;font-weight:700;
          background:#f5f7fa;border-radius:8px;padding:16px;text-align:center;
          margin:16px 0;color:#1f2933;">{code}</p>"""


def otp_email(code: str, purpose_line: str, ttl_minutes: int) -> tuple[str, str]:
    """Build (plain_text, html) for a one-time-code email."""
    expiry_line = f"The code is valid for {ttl_minutes} minute(s)."
    safety_line = (
        "Queue RX will never ask you for this code by phone, chat or email. "
        "Please do not share it with anyone."
    )
    ignore_line = (
        "If you did not request this code, no action is needed — "
        "nothing has been changed on your account."
    )

    text = (
        f"{purpose_line}\n\n"
        f"Your verification code is: {code}\n\n"
        f"{expiry_line}\n\n"
        f"{safety_line}\n\n"
        f"{ignore_line}\n\n"
        f"— {settings.EMAIL_SENDER_IDENTITY}\n"
    )

    html = _shell(
        heading="Your verification code",
        # Deliberately does not contain the code: the preview line is
        # visible on a locked phone screen.
        preheader=f"A one-time code for Queue RX, valid for {ttl_minutes} minute(s).",
        content=(
            f"<p style='margin:0;font-size:14px;'>{escape(purpose_line)}</p>"
            + _CODE_BLOCK.format(code=escape(code))
            + f"<p style='font-size:13px;color:#52606d;margin:0 0 10px;'>{escape(expiry_line)}</p>"
            + f"<p style='font-size:13px;color:#52606d;margin:0;'>{escape(safety_line)}</p>"
        ),
        footer=ignore_line,
    )
    return text, html


def transfer_request_email(
    pharmacy_name: str,
    current_owner_name: str,
    current_owner_email: str,
    expires_at_str: str,
) -> tuple[str, str]:
    """Notification mailed to the *prospective* new owner when a transfer opens."""
    footer = "If you were not expecting this, decline the request — no change is made until you accept."
    text = (
        f"{current_owner_name} ({current_owner_email}) has requested to transfer "
        f"ownership of the pharmacy \"{pharmacy_name}\" to you on Queue RX.\n\n"
        f"Open Queue RX and go to Ownership Transfers to accept or decline. "
        f"Accepting requires a verification code sent to this address.\n\n"
        f"This request expires on {expires_at_str} UTC.\n\n"
        f"{footer}\n\n"
        f"— {settings.EMAIL_SENDER_IDENTITY}\n"
    )
    html = _shell(
        heading="You have been offered pharmacy ownership",
        preheader=f"{current_owner_name} wants to transfer {pharmacy_name} to you.",
        content=(
            f"<p style='margin:0 0 12px;font-size:14px;'><strong>{escape(current_owner_name)}</strong> "
            f"({escape(current_owner_email)}) has requested to transfer ownership of "
            f"<strong>{escape(pharmacy_name)}</strong> to you.</p>"
            f"<p style='margin:0 0 12px;font-size:14px;'>Open Queue RX and go to "
            f"<strong>Ownership Transfers</strong> to accept or decline. Accepting "
            f"requires a verification code sent to this address.</p>"
            f"<p style='font-size:13px;color:#52606d;margin:0;'>This request expires on "
            f"<strong>{escape(expires_at_str)} UTC</strong>.</p>"
        ),
        footer=footer,
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
        f"\"{pharmacy_name}\".\n\n{tail}\n\n"
        f"— {settings.EMAIL_SENDER_IDENTITY}\n"
    )
    html = _shell(
        heading=f"Ownership transfer {verb}",
        preheader=f"{new_owner_name} {verb} the transfer of {pharmacy_name}.",
        content=(
            f"<p style='margin:0 0 12px;font-size:14px;'><strong>{escape(new_owner_name)}</strong> has "
            f"<strong>{escape(verb)}</strong> your request to transfer ownership of "
            f"<strong>{escape(pharmacy_name)}</strong>.</p>"
            f"<p style='font-size:13px;color:#52606d;margin:0;'>{escape(tail)}</p>"
        ),
        footer="You are receiving this because you started this ownership transfer in Queue RX.",
    )
    return text, html
