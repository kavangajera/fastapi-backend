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
    city: str | None = Field(None, description="City.", examples=["Mumbai"])
    state: str | None = Field(None, description="State / province.", examples=["Maharashtra"])
    zip_code: str | None = Field(None, description="ZIP / postal code.", examples=["400001"])
    store_code: str | None = Field(
        None, description="Store / outlet code.", examples=["STORE-01"]
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "pharmacy_title": "MediCare Pharmacy",
                "pharmacy_location": "123 Health Street, Mumbai",
                "city": "Mumbai",
                "state": "Maharashtra",
                "zip_code": "400001",
                "store_code": "STORE-01",
                "device_id": "a1B2c3",
            }
        }
    }
