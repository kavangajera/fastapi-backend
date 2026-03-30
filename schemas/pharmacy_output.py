from pydantic import BaseModel, Field
from typing import Optional
from schemas.user_output import UserOutput


class PharmacyOutput(BaseModel):
    """Frontend-facing pharmacy output — internal DB field names hidden via aliases."""
    id: int = Field(alias="pharmacy_id")
    name: str = Field(alias="name")
    address: str = Field(alias="address")
    owner: Optional[UserOutput] = Field(default=None, alias="owner")

    class Config:
        from_attributes = True
        populate_by_name = True
