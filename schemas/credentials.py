"""
schemas/credentials.py
──────────────────────
The one place email and password rules are defined.

Signup, forgot-password and ownership-transfer all take an email address,
and signup and password-reset both take a password. Keeping the rules here
means a password that is acceptable at signup is still acceptable at reset
(and vice versa) — a mismatch would let someone register a password they
can never re-create after a reset.

Emails are typed as plain `str` throughout the codebase rather than
pydantic's `EmailStr`, so the shape check lives in `normalize_email`; it
also lowercases, which is what makes a stored address comparable.
"""

from __future__ import annotations

import re

MIN_PASSWORD_LENGTH = 8

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

# Local-part cap (RFC 5321) — also what `username` is derived from at
# signup, where the column is VARCHAR(100).
_MAX_EMAIL_LENGTH = 255
_MAX_LOCAL_PART_LENGTH = 64


def normalize_email(value: str) -> str:
    """Trim + lowercase, and reject anything that is not email-shaped."""
    value = (value or "").strip().lower()
    if len(value) > _MAX_EMAIL_LENGTH:
        raise ValueError("Email address is too long")
    if not _EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address")
    if len(value.split("@")[0]) > _MAX_LOCAL_PART_LENGTH:
        raise ValueError("Email address is too long")
    return value


def validate_password(value: str) -> str:
    """Minimum policy, applied identically wherever a password is set."""
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long")
    # Argon2 itself has no practical input limit, but an unbounded password
    # is an easy way to burn CPU on the hashing path.
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters long")
    if value.strip() != value:
        raise ValueError("Password must not start or end with whitespace")
    return value
