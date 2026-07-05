from pydantic import BaseModel, Field


class Login_Input_User_Schema(BaseModel):
    """
    Credentials payload for authenticating an existing user.

    On success the response contains an ``access_token`` (JWT) and a
    ``refresh_token`` is set as an httpOnly cookie.
    """

    user_email: str = Field(
        ...,
        description="Registered email address of the user.",
        examples=["user2@gmail.com"],
    )
    input_password: str = Field(
        ...,
        description="Plain-text password that was set during signup.",
        examples=["123456"],
    )
    device_id: str | None = Field(
        None,
        min_length=6,
        max_length=6,
        pattern=r"^[A-Za-z0-9]+$",
        description=(
            "Client-generated 6-char alphanumeric device id. If present and "
            "well-formed it is adopted; otherwise the server generates one and "
            "returns it as ``device_id`` in the response for the client to store."
        ),
        examples=["a1B2c3"],
    )
    source: str | None = Field(
        None,
        description="Platform source code (e.g. 'AN001'). Pinned to the device and "
        "used as the prefix of every record identifier generated for it.",
        examples=["AN001"],
    )
    source_platform: str | None = Field(
        None,
        description="Human-readable platform label.",
        examples=["Android"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_email": "user2@gmail.com",
                "input_password": "123456",
                "device_id": "a1B2c3",
                "source": "AN001",
                "source_platform": "Android",
            }
        }
    }
