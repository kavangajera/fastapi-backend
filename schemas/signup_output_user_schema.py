from pydantic import BaseModel

class Signup_Output_User_Schema(BaseModel):

    user_id :int
    username :str
    email :str
    contact:str
    

