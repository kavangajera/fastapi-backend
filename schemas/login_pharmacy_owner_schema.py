from pydantic import BaseModel

class Login_Pharmacy_Owner_Schema(BaseModel):

    username:str
    input_password:str
