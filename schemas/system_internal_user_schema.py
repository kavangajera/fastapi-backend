from pydantic import BaseModel

from core.enums import UserRole


class System_Internal_User_Schema(BaseModel):
    user_id: int
    username: str
    role: UserRole
    medical_store_id: int | None = None
