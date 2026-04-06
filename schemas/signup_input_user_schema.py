from pydantic import BaseModel, Field


class Signup_Input_User_Schema(BaseModel):
    """
    Registration payload for creating a new **PHARMACY_OWNER** account.

    All fields are required.  After a successful signup the user can log in
    with ``user_email`` and ``input_password``.
    """

    user_name: str = Field(
        ...,
        description="Display name for the new user. Must be unique across the platform.",
        examples=["user2"],
    )
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
    contact: str = Field(
        ...,
        description="Phone / contact number of the user (digits only, 10+ chars recommended).",
        examples=["1234567890"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_name": "user2",
                "user_email": "user2@gmail.com",
                "input_password": "123456",
                "contact": "1234567890",
            }
        }
    }
