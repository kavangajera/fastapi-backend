from pydantic import BaseModel, Field
from typing import Optional
from schemas.user_output import UserOutput
from schemas.address_schema import AddressOutput


class PharmacyOutput(BaseModel):
    """Frontend-facing pharmacy output — internal DB field names hidden via aliases."""

    id: int = Field(
        ...,
        alias="pharmacy_id",
        description="Unique numeric identifier of the pharmacy.",
        examples=[2],
    )
    name: str = Field(
        ...,
        alias="name",
        description="Name / title of the pharmacy.",
        examples=["Deva'sShop"],
    )
    code: Optional[str] = Field(
        default=None,
        alias="code",
        description="Store code of the pharmacy.",
        examples=["DVA-001"],
    )
    address: Optional[AddressOutput] = Field(
        default=None,
        alias="address_rel",
        description="Address details of the pharmacy.",
    )
    owner: Optional[UserOutput] = Field(
        default=None,
        alias="owner",
        description="Owner details (populated when the endpoint joins user data). Null when not loaded.",
    )

    class Config:
        from_attributes = True
        populate_by_name = True
