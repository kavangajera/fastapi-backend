from pydantic import BaseModel

class Pharmacy_Input_Schema(BaseModel):
    name:str
    address:str

    model_config = {
        "json_schema_extra": {
             "example": {
                "name": "Enter Your pharmacy name",
                "address":"Dummy address"
            }
        }
    }
