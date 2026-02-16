from pydantic import BaseModel

class Signup_Input_Pharmacy_Owner_Schema(BaseModel):

    username :str
    email :str
    input_password:str
    contact:str
    

