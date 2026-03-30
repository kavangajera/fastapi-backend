from pydantic import BaseModel

class Signup_Input_User_Schema(BaseModel):

    user_name :str
    user_email :str
    input_password:str
    contact:str
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_name":"DummyUser",
                "user_email": "Every time add new email because of it is unique",
                "input_password": "123456",
                "contact":"1234567890"
            }
        }
    }
