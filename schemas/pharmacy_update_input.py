from pydantic import BaseModel, Field
from typing import Optional


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
    pharmacy_location: Optional[str] = Field(
        None,
        description="New street address. Omit to keep the current value.",
        examples=["456 Wellness Ave, Pune"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "pharmacy_title": "Deva's Health Hub",
                "pharmacy_location": "456 Wellness Ave, Pune",
            }
        }
    }
