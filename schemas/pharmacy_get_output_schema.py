from typing import Optional
from pydantic import BaseModel,Field
from schemas.user_get_output import UserGetOutput

class PharmacyGetOutputSchema(BaseModel):
    pharmacy_id:int=Field(alias="pharmacy_id")
    pharmacy_owner: Optional[UserGetOutput] = Field(default=None, alias="owner")    
    pharmacy_name:str=Field(alias="name")
    pharmacy_address:str=Field(alias="address")

    class Config:
        from_attributes = True
        populate_by_name = True