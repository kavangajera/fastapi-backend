from pydantic import BaseModel

class System_Internal_User_Schema(BaseModel):
    user_id :int
    username :str
    role :str