from pydantic import BaseModel


class UserUpdateSchema(BaseModel):
    username: str | None = None
    user_email: str | None = None
    contact: str | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "UpdatedUsername",
                "user_email": "updated@email.com",
                "contact": "9876543210",
            }
        }
    }
