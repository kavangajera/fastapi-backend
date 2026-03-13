from typing import Optional
from pydantic import BaseModel,Field
from schemas.user_get_output import UserGetOutput

class PharmacyGetOutputSchema(BaseModel):
    PharmacyId:int=Field(alias="pharmacy_id")
    PharmacyOwner: Optional[UserGetOutput] = Field(default=None, alias="owner")    
    PharmacyName:str=Field(alias="name")
    PharmacyAddress:str=Field(alias="address")

    class Config:
        from_attributes = True
        populate_by_name = True