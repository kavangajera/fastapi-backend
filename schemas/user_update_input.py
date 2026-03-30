from pydantic import BaseModel, Field
from typing import Optional


class UserUpdateInput(BaseModel):
    """Frontend-facing update input — clean field names, all optional for partial updates."""
    name: Optional[str] = Field(None, description="New display name")
    user_email: Optional[str] = Field(None, description="New email address")
    phone: Optional[str] = Field(None, description="New contact number")

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "NewUsername",
                "user_email": "new@email.com",
                "phone": "9876543210"
            }
        }
    }
