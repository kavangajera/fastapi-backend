from pydantic import Field

from schemas.audit_input import AuditInputFields


class PharmacyUpdateInput(AuditInputFields):
    """
    Partial-update payload for an existing pharmacy.

    All fields are optional — only the fields you include will be updated.
    Pass the pharmacy ID as a path parameter (``ph_id``).
    """

    pharmacy_title: str | None = Field(
        None,
        description="New name / title for the pharmacy. Omit to keep the current value.",
        examples=["Deva's Health Hub"],
    )
    pharmacy_location: str | None = Field(
        None,
        description="New street address. Omit to keep the current value.",
        examples=["456 Wellness Ave, Pune"],
    )
    city: str | None = Field(None, description="City.", examples=["Pune"])
    state: str | None = Field(None, description="State / province.", examples=["Maharashtra"])
    zip_code: str | None = Field(None, description="ZIP / postal code.", examples=["411001"])
    store_code: str | None = Field(
        None, description="Store / outlet code.", examples=["STORE-01"]
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "pharmacy_title": "Deva's Health Hub",
                "pharmacy_location": "456 Wellness Ave, Pune",
                "city": "Pune",
                "state": "Maharashtra",
                "zip_code": "411001",
                "store_code": "STORE-01",
                "device_id": "a1B2c3",
            }
        }
    }
