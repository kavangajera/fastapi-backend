from pydantic import BaseModel, Field


class MessageOutput(BaseModel):
    """Standard message response for delete / action confirmations."""

    message: str = Field(
        ...,
        description="Human-readable confirmation message describing the action that was performed.",
        examples=["User deleted successfully"],
    )
