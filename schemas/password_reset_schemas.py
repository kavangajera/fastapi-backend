"""
schemas/password_reset_schemas.py
─────────────────────────────────
Request payloads for the three-step forgot-password flow.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# The email/password rules live in `schemas.credentials` so signup and reset
# cannot drift apart. Re-exported here because callers already import them
# from this module.
from schemas.credentials import (  # noqa: F401  (re-export)
    MIN_PASSWORD_LENGTH,
    normalize_email,
    validate_password,
)


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
        return validate_password(value)
