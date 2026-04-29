from pydantic import BaseModel, Field
from typing import Optional
from schemas.address_schema import AddressInput


class Pharmacy_Input_Schema(BaseModel):
    """
    Payload for creating a new pharmacy.

    The pharmacy will be automatically linked to the currently authenticated
    user (the owner).  Only OWNER and ADMIN roles can create pharmacies.
    """

    pharmacy_title: str = Field(
        ...,
        description="Name / title of the pharmacy. Displayed across the platform.",
        examples=["MediCare Pharmacy"],
    )
    pharmacy_code: Optional[str] = Field(
        None,
        description="Optional unique store code for the pharmacy.",
        examples=["MED-001"],
    )
    address: Optional[AddressInput] = Field(
        None,
        description="Optional address details. If omitted, an empty address record is created.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "pharmacy_title": "MediCare Pharmacy",
                "pharmacy_code": "MED-001",
                "address": {
                    "address_line_1": "123 Health Street",
                    "address_line_2": "Suite 200",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "zip_code": "400001",
                },
            }
        }
    }
