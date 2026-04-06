from pydantic import BaseModel, Field


class Signup_Input_User_Technician_Schema(BaseModel):
    """
    Registration payload for creating a new **TECHNICIAN** account.

    A technician must be linked to an existing pharmacy via ``pharmacy_id``.
    Only OWNER and ADMIN roles can call the create-technician endpoint.
    """

    user_name: str = Field(
        ...,
        description="Display name for the new technician.",
        examples=["User2Tech"],
    )
    user_email: str = Field(
        ...,
        description="Email address for the technician. Must be unique across the platform.",
        examples=["User2Tech@gmail.com"],
    )
    input_password: str = Field(
        ...,
        description="Plain-text password (min 6 characters). Will be hashed server-side with Argon2.",
        examples=["123456"],
    )
    contact: str = Field(
        ...,
        description="Phone / contact number of the technician.",
        examples=["1234567890"],
    )
    pharmacy_id: int = Field(
        ...,
        description="ID of the pharmacy this technician will be assigned to. Must be an existing pharmacy owned by the authenticated user.",
        examples=[2],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_name": "User2Tech",
                "user_email": "User2Tech@gmail.com",
                "input_password": "123456",
                "contact": "1234567890",
                "pharmacy_id": 2,
            }
        }
    }
