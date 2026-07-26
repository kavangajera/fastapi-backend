from pydantic import Field, field_validator

from schemas.audit_input import AuditInputFields
from schemas.credentials import MIN_PASSWORD_LENGTH, normalize_email, validate_password


class Signup_Input_User_Schema(AuditInputFields):
    """
    Step 1 of registration — ``POST /user/signup``.

    This payload does **not** create an account. It stages the credentials
    and mails a verification code; the account is created only by
    ``POST /user/verify-signup-otp``.

    Only ``user_email`` and ``input_password`` are required from the
    frontend. The backend derives the username from the email (the part
    before ``@``) and defaults the contact number to ``1234567890``.
    """

    user_email: str = Field(
        ...,
        description=(
            "Email address used for login. Must be unique — a duplicate is "
            "rejected with 409. Normalized to lowercase; the verification "
            "code is sent here, so a typo means no code arrives."
        ),
        examples=["user2@gmail.com"],
    )
    input_password: str = Field(
        ...,
        description=(
            f"Plain-text password (min {MIN_PASSWORD_LENGTH} characters). Hashed "
            "with Argon2id immediately and never stored in the clear — not even "
            "while the signup is pending."
        ),
        examples=["Secret123!"],
    )

    @field_validator("user_email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("input_password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return validate_password(value)

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_email": "user2@gmail.com",
                "input_password": "Secret123!",
                "device_id": "a1B2c3",
            }
        }
    }
