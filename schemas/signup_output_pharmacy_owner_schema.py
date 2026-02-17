from pydantic import BaseModel

class Signup_Output_Pharmacy_Owner_Schema(BaseModel):

    owner_id :int
    username :str
    email :str
    contact:str
    

