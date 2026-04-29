from pydantic import BaseModel, Field
from typing import Optional
from schemas.address_schema import AddressUpdateInput


class PharmacyUpdateInput(BaseModel):
    """
    Partial-update payload for an existing pharmacy.

    All fields are optional — only the fields you include will be updated.
    Pass the pharmacy ID as a path parameter (``ph_id``).
    """

    pharmacy_title: Optional[str] = Field(
        None,
        description="New name / title for the pharmacy. Omit to keep the current value.",
        examples=["Deva's Health Hub"],
    )
    pharmacy_code: Optional[str] = Field(
        None,
        description="New store code. Omit to keep the current value.",
        examples=["DVA-002"],
    )
    address: Optional[AddressUpdateInput] = Field(
        None,
        description="Partial address update. Only included sub-fields are changed.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "pharmacy_title": "Deva's Health Hub",
                "pharmacy_code": "DVA-002",
                "address": {
                    "city": "Pune",
                    "state": "Maharashtra",
                },
            }
        }
    }
