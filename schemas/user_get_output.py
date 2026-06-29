from pydantic import BaseModel, Field

from core.enums import UserRole
from schemas.audit_fields import AuditFields
from schemas.user_state_fields import UserStateFields


class UserGetOutput(AuditFields, UserStateFields):
    """User data returned by GET endpoints (list users, get profile, etc.)."""

    user_id: int = Field(
        ...,
        alias="user_id",
        description="Unique numeric identifier of the user.",
        examples=[4],
    )
    username: str = Field(
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
    contact: str = Field(
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
