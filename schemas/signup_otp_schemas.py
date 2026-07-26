"""
schemas/signup_otp_schemas.py
─────────────────────────────
Payloads for steps 2 and 3 of the OTP-verified signup flow. Step 1 reuses
``Signup_Input_User_Schema``.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from schemas.audit_input import AuditInputFields
from schemas.credentials import normalize_email


class VerifySignupOtpInput(AuditInputFields):
    """Step 2 — the code that actually creates the account."""

    user_email: str = Field(
        ...,
        description="The same email the code was sent to.",
        examples=["user2@gmail.com"],
    )
    otp_code: str = Field(
        ...,
        min_length=4,
        max_length=10,
        description="The numeric code from the email.",
        examples=["482913"],
    )

    @field_validator("user_email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return normalize_email(value)


class ResendSignupOtpInput(AuditInputFields):
    """Re-send the code for a signup already in progress.

    The password is not repeated — it is already staged from step 1, so a
    resend cannot be used to change it.
    """

    user_email: str = Field(
        ...,
        description="Email of the signup awaiting verification.",
        examples=["user2@gmail.com"],
    )

    @field_validator("user_email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return normalize_email(value)
