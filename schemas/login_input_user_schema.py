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

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_email": "user2@gmail.com",
                "input_password": "123456",
            }
        }
    }
