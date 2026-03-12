from pydantic import BaseModel

class Signup_Input_User_Schema(BaseModel):

    username :str
    email :str
    input_password:str
    contact:str
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "username":"DummyUser",
                "email": "Every time add new email because of it is unique",
                "input_password": "123456",
                "contact":"1234567890"
            }
        }
    }
