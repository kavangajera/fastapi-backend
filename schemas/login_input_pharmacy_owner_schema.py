from pydantic import BaseModel

class Login_Input_Pharmacy_Owner_Schema(BaseModel):

    email:str
    input_password:str
