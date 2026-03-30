from pydantic import BaseModel

class Login_Input_User_Schema(BaseModel):
    user_email: str
    input_password: str
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_email": "user2",
                "input_password": "123456"
            }
        }
    }