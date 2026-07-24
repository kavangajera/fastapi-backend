"""
schemas/password_reset_schemas.py
─────────────────────────────────
Request payloads for the three-step forgot-password flow.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# Kept deliberately modest — signup does not enforce a policy today, so a
# stricter rule here would let users lock themselves into a password they
# cannot re-create.
MIN_PASSWORD_LENGTH = 8

# Plain `str` + this check rather than pydantic's EmailStr: the rest of the
# codebase types emails as `str`, and EmailStr would pull in the optional
# `email-validator` dependency for no real gain here.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def normalize_email(value: str) -> str:
    value = (value or "").strip().lower()
    if not _EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address")
    return value


def _validate_password(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long")
    if value.strip() != value:
        raise ValueError("Password must not start or end with whitespace")
    return value


class ForgotPasswordInput(BaseModel):
    """Step 1 — ask for a reset code."""

    user_email: str = Field(
        ...,
        description="Email address of the account to reset.",
        examples=["owner@pharmacy.com"],
    )

    @field_validator("user_email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return normalize_email(value)


class VerifyResetOtpInput(BaseModel):
    """Step 2 — exchange the emailed code for a short-lived reset token."""

    user_email: str = Field(
        ...,
        description="The same email the code was sent to.",
        examples=["owner@pharmacy.com"],
    )

    @field_validator("user_email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return normalize_email(value)

    otp_code: str = Field(
        ...,
        min_length=4,
        max_length=10,
        description="The numeric code from the email.",
        examples=["482913"],
    )


class ResetPasswordInput(BaseModel):
    """Step 3 — set the new password using the reset token."""

    reset_token: str = Field(
        ...,
        description="Token returned by `POST /user/verify-reset-otp`.",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )
    new_password: str = Field(
        ...,
        description=f"New password (min {MIN_PASSWORD_LENGTH} characters).",
        examples=["MyNewPassw0rd!"],
    )

    @field_validator("new_password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return _validate_password(value)
