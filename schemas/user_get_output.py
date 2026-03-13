from pydantic import BaseModel,Field
from core.enums import UserRole

class UserGetOutput(BaseModel):
    UserId :int=Field(alias="user_id")
    Username : str=Field(alias="username")
    Email : str=Field(alias="email")
    Contact :str=Field(alias="contact_number")
    Role:UserRole=Field(alias="role")

    class Config:
        from_attributes = True
        populate_by_name = True