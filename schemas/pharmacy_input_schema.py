from pydantic import BaseModel, Field


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
    pharmacy_location: str = Field(
        ...,
        description="Physical street address of the pharmacy.",
        examples=["123 Health Street, Mumbai"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "pharmacy_title": "MediCare Pharmacy",
                "pharmacy_location": "123 Health Street, Mumbai",
            }
        }
    }
