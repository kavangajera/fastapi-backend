"""
scripts/check_smtp.py
---------------------
Verify the SMTP credentials in `.env` actually work, without touching the
API or the database. Run this first whenever verification codes are not
arriving - it isolates "email is broken" from "the flow is broken".

Usage:
    uv run python -m scripts.check_smtp                 # send to yourself
    uv run python -m scripts.check_smtp someone@x.com   # send elsewhere

Exit code is 0 on success, 1 on failure.
"""

from __future__ import annotations

import asyncio
import sys

from core.config import settings
from services import email_service


def _mask(secret: str) -> str:
    if not secret:
        return "(empty)"
    return f"{secret[:2]}{'*' * max(0, len(secret) - 4)}{secret[-2:]}  [{len(secret)} chars]"


async def main() -> int:
    recipient = sys.argv[1] if len(sys.argv) > 1 else settings.SMTP_USERNAME

    # ASCII-only output: the default Windows console is cp1252 and raises
    # UnicodeEncodeError on box-drawing characters.
    print("SMTP configuration")
    print("------------------")
    print(f"  host      : {settings.SMTP_HOST}:{settings.SMTP_PORT}")
    print(f"  username  : {settings.SMTP_USERNAME or '(empty)'}")
    print(f"  password  : {_mask(settings.SMTP_PASSWORD)}")
    print(f"  from      : {settings.SMTP_FROM_EMAIL or settings.SMTP_USERNAME or '(empty)'}")
    print(f"  TLS / SSL : {settings.SMTP_USE_TLS} / {settings.SMTP_USE_SSL}")
    print(f"  recipient : {recipient or '(none)'}")
    print()

    if not email_service.is_configured():
        print("NOT CONFIGURED - set SMTP_USERNAME and SMTP_PASSWORD in .env.")
        print("The app still runs: codes are written to the log instead of emailed.")
        return 1

    if not recipient:
        print("No recipient. Pass one as an argument.")
        return 1

    if " " in settings.SMTP_PASSWORD:
        print("WARNING: the password contains spaces. Google displays App Passwords")
        print("         as 'abcd efgh ijkl mnop' but they must be pasted without spaces.")
        print()

    print("Sending test email...")
    sent = await email_service.send_email(
        recipient,
        "Queue RX - SMTP test",
        "If you are reading this, Queue RX can send email. "
        "Password resets and ownership-transfer codes will be delivered.\n",
        raise_on_failure=False,
    )

    if sent:
        print(f"\nSUCCESS - test email sent to {recipient}. Check the inbox (and spam).")
        return 0

    print("\nFAILED - see the error above. Most common causes:")
    print("  * Gmail: using the account password instead of an App Password")
    print("    -> https://myaccount.google.com/apppasswords (2FA must be enabled)")
    print("  * App Password pasted with spaces - remove them")
    print("  * Port/TLS mismatch - use 587 + SMTP_USE_TLS, or 465 + SMTP_USE_SSL")
    print("  * Network/firewall blocking outbound SMTP")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
