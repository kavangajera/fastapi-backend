from pydantic import BaseModel

class Login_Input_User_Schema(BaseModel):
    email: str
    input_password: str
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "user2",
                "input_password": "123456"
            }
        }
    }