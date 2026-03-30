from pydantic import BaseModel
from typing import Optional

class UserUpdateSchema(BaseModel):
    username: Optional[str] = None
    user_email: Optional[str] = None
    contact: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "UpdatedUsername",
                "user_email": "updated@email.com",
                "contact": "9876543210"
            }
        }
    }
