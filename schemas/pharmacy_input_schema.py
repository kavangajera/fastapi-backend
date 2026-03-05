from pydantic import BaseModel

class Pharmacy_Input_Schema(BaseModel):
    owner_id: int
    name:str
    address:str

