from pydantic import BaseModel, Field


class Impersonate_Input_Schema(BaseModel):
    """Request body for an ADMIN to impersonate another user (Super Admin feature)."""

    user_id: int = Field(
        ...,
        description="ID of the user to impersonate.",
        examples=[4],
    )
    medical_store_id: int | None = Field(
        default=None,
        description="Optional pharmacy ID to pre-select for the impersonated session.",
        examples=[2],
    )
