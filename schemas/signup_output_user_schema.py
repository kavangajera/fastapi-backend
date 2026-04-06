from pydantic import BaseModel, Field


class Signup_Output_User_Schema(BaseModel):
    """User data returned after a successful signup."""

    user_id: int = Field(
        ...,
        description="Auto-generated unique identifier for the newly created user.",
        examples=[4],
    )
    username: str = Field(
        ...,
        description="Display name that was set during registration.",
        examples=["user2"],
    )
    email: str = Field(
        ...,
        description="Email address that was registered.",
        examples=["user2@gmail.com"],
    )
    contact: str = Field(
        ...,
        description="Contact / phone number that was registered.",
        examples=["1234567890"],
    )
