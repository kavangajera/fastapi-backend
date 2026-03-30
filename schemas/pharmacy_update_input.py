from pydantic import BaseModel
from typing import Optional


class PharmacyUpdateInput(BaseModel):
    """Frontend-facing pharmacy update input — all optional for partial updates."""
    pharmacy_title: Optional[str] = None
    pharmacy_location: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "pharmacy_title": "New Pharmacy Name",
                "pharmacy_location": "New Address"
            }
        }
    }
