from pydantic import BaseModel, Field
from typing import Optional


class UserUpdateInput(BaseModel):
    """
    Partial-update payload for a user profile.

    All fields are optional — only the fields you include will be updated.
    Use ``PUT /user/update/me`` to update yourself, or
    ``PUT /user/update/{user_id}`` (OWNER/ADMIN only) to update another user.
    """

    name: Optional[str] = Field(
        None,
        description="New display name for the user. Omit to keep the current value.",
        examples=["UpdatedUser2"],
    )
    user_email: Optional[str] = Field(
        None,
        description="New email address. Must be unique across the platform. Omit to keep the current value.",
        examples=["updated_user2@gmail.com"],
    )
    phone: Optional[str] = Field(
        None,
        description="New contact / phone number. Omit to keep the current value.",
        examples=["9876543210"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "UpdatedUser2",
                "user_email": "updated_user2@gmail.com",
                "phone": "9876543210",
            }
        }
    }
