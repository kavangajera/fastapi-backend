from pydantic import BaseModel, Field
from typing import Optional


class AddressInput(BaseModel):
    """Optional address fields when creating a pharmacy."""

    address_line_1: Optional[str] = Field(
        None,
        description="Primary street address line.",
        examples=["123 Health Street"],
    )
    address_line_2: Optional[str] = Field(
        None,
        description="Secondary address line (apt, suite, etc.).",
        examples=["Suite 200"],
    )
    city: Optional[str] = Field(
        None,
        description="City name.",
        examples=["Mumbai"],
    )
    state: Optional[str] = Field(
        None,
        description="State or province.",
        examples=["Maharashtra"],
    )
    zip_code: Optional[str] = Field(
        None,
        description="Postal / ZIP code.",
        examples=["400001"],
    )


class AddressUpdateInput(BaseModel):
    """Partial-update payload for an address. Only included fields are updated."""

    address_line_1: Optional[str] = Field(None, description="Primary street address line.")
    address_line_2: Optional[str] = Field(None, description="Secondary address line.")
    city: Optional[str] = Field(None, description="City name.")
    state: Optional[str] = Field(None, description="State or province.")
    zip_code: Optional[str] = Field(None, description="Postal / ZIP code.")


class AddressOutput(BaseModel):
    """Serialised address returned in pharmacy responses."""

    address_id: int = Field(..., description="Unique address identifier.", examples=[1])
    address_line_1: Optional[str] = Field(None, examples=["123 Health Street"])
    address_line_2: Optional[str] = Field(None, examples=["Suite 200"])
    city: Optional[str] = Field(None, examples=["Mumbai"])
    state: Optional[str] = Field(None, examples=["Maharashtra"])
    zip_code: Optional[str] = Field(None, examples=["400001"])

    class Config:
        from_attributes = True
