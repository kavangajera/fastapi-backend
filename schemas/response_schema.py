from pydantic import BaseModel
from typing import Any

class Response_Schema(BaseModel):
    statusCode:int
    data:Any