from pydantic import BaseModel, Field


class TokenData(BaseModel):
    """Decoded JWT token payload (used internally for auth verification)."""

    username: str = Field(
        ...,
        description="Display name of the authenticated user (from the JWT claim).",
        examples=["user2"],
    )
    owner_id: int = Field(
        ...,
        description="User ID of the authenticated user (from the JWT claim).",
        examples=[4],
    )
    expire: int = Field(
        ...,
        description="Token expiration time as a Unix timestamp (seconds since epoch).",
        examples=[1743936000],
    )