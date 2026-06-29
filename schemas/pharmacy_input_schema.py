from pydantic import Field

from schemas.audit_input import AuditInputFields


class Pharmacy_Input_Schema(AuditInputFields):
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
                "record_Identifier": "AN001111111STO000002",
                "update_record_Identifier": None,
            }
        }
    }
