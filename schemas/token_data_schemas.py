from pydantic import BaseModel
class TokenData(BaseModel):
    username:str
    owner_id:int
    expire:int