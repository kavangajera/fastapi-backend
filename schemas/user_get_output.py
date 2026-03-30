from pydantic import BaseModel,Field
from core.enums import UserRole

class UserGetOutput(BaseModel):
    user_id :int=Field(alias="user_id")
    username : str=Field(alias="username")
    email : str=Field(alias="email")
    contact :str=Field(alias="contact_number")
    role:UserRole=Field(alias="role")

    class Config:
        from_attributes = True
        populate_by_name = True