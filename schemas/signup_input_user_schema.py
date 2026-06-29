from pydantic import Field

from schemas.audit_input import AuditInputFields


class Signup_Input_User_Schema(AuditInputFields):
    """
    Registration payload for creating a new **PHARMACY_OWNER** account.

    Only ``user_email`` and ``input_password`` are required from the frontend.
    The backend derives the username from the email (the part before ``@``)
    and defaults the contact number to ``1234567890``.
    """

    user_email: str = Field(
        ...,
        description="Email address used for login. Must be unique — duplicate emails are rejected.",
        examples=["user2@gmail.com"],
    )
    input_password: str = Field(
        ...,
        description="Plain-text password (min 6 characters). Will be hashed server-side with Argon2.",
        examples=["123456"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_email": "user2@gmail.com",
                "input_password": "123456",
                "record_Identifier": "AN001111111USR000001",
                "update_record_Identifier": None,
            }
        }
    }
