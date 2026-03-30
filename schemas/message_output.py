from pydantic import BaseModel


class MessageOutput(BaseModel):
    """Standard message response for delete/action confirmations."""
    message: str
