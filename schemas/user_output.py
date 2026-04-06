from pydantic import BaseModel, Field
from typing import Optional
from core.enums import UserRole


class UserOutput(BaseModel):
    """Frontend-facing user output — internal DB field names are hidden via aliases."""

    id: int = Field(
        ...,
        alias="user_id",
        description="Unique numeric identifier of the user.",
        examples=[4],
    )
    name: str = Field(
        ...,
        alias="username",
        description="Display name of the user.",
        examples=["user2"],
    )
    email: str = Field(
        ...,
        alias="email",
        description="Registered email address.",
        examples=["user2@gmail.com"],
    )
    phone: str = Field(
        ...,
        alias="contact_number",
        description="Contact / phone number.",
        examples=["1234567890"],
    )
    role: UserRole = Field(
        ...,
        alias="role",
        description="Role assigned to the user. One of: OWNER, TECHNICIAN, ADMIN.",
        examples=["OWNER"],
    )

    class Config:
        from_attributes = True
        populate_by_name = True
