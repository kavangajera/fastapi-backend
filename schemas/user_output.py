from pydantic import Field

from core.enums import UserRole
from schemas.audit_fields import AuditFields
from schemas.user_state_fields import UserStateFields


class UserOutput(AuditFields, UserStateFields):
    """Frontend-facing user output — internal DB field names are hidden via aliases."""

    user_id: int = Field(
        ...,
        validation_alias="user_id",
        description="Unique numeric identifier of the user.",
        examples=[4],
    )
    email: str = Field(
        ...,
        alias="email",
        description="Registered email address.",
        examples=["user2@gmail.com"],
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
