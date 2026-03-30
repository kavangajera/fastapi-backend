from pydantic import BaseModel

class Pharmacy_Input_Schema(BaseModel):
    pharmacy_title:str
    pharmacy_location:str

    model_config = {
        "json_schema_extra": {
             "example": {
                "pharmacy_title": "Enter Your pharmacy name",
                "pharmacy_location":"Dummy address"
            }
        }
    }
