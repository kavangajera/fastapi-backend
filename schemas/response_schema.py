from pydantic import BaseModel
from typing import Any

class Response_Schema(BaseModel):
    status_code: int
    message: str
    data: Any