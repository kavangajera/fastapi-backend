from pydantic import BaseModel

class Pharmacy_Owner_Schema(BaseModel):

    owner_id :int
    username :str
    email :str
    input_password:str
    contact:str
    

