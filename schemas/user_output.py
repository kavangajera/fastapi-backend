from pydantic import BaseModel, Field
from typing import Optional
from core.enums import UserRole


class UserOutput(BaseModel):
    """Frontend-facing user output — internal DB field names are hidden via aliases."""
    id: int = Field(alias="user_id")
    name: str = Field(alias="username")
    email: str = Field(alias="email")
    phone: str = Field(alias="contact_number")
    role: UserRole = Field(alias="role")

    class Config:
        from_attributes = True
        populate_by_name = True
