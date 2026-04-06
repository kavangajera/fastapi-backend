from typing import Optional
from pydantic import BaseModel, Field
from schemas.user_get_output import UserGetOutput


class PharmacyGetOutputSchema(BaseModel):
    """Pharmacy data returned by GET endpoints (list pharmacies, search, etc.)."""

    pharmacy_id: int = Field(
        ...,
        alias="pharmacy_id",
        description="Unique numeric identifier of the pharmacy.",
        examples=[2],
    )
    pharmacy_owner: Optional[UserGetOutput] = Field(
        default=None,
        alias="owner",
        description="Owner user details (populated when the endpoint joins user data). Null when not loaded.",
    )
    pharmacy_name: str = Field(
        ...,
        alias="name",
        description="Name / title of the pharmacy.",
        examples=["Deva'sShop"],
    )
    pharmacy_address: str = Field(
        ...,
        alias="address",
        description="Physical street address of the pharmacy.",
        examples=["skfnoajnf"],
    )

    class Config:
        from_attributes = True
        populate_by_name = True