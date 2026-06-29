from pydantic import BaseModel, Field

from schemas.audit_fields import AuditFields
from schemas.user_output import UserOutput


class PharmacyOutput(AuditFields, BaseModel):
    """Frontend-facing pharmacy output — internal DB field names hidden via aliases."""

    id: int = Field(
        ...,
        alias="medical_store_id",
        description="Unique numeric identifier of the pharmacy.",
        examples=[2],
    )
    name: str = Field(
        ...,
        alias="name",
        description="Name / title of the pharmacy.",
        examples=["Deva'sShop"],
    )
    address: str = Field(
        ...,
        alias="address",
        description="Physical street address of the pharmacy.",
        examples=["skfnoajnf"],
    )
    owner: UserOutput | None = Field(
        default=None,
        alias="owner",
        description="Owner details (populated when the endpoint joins user data). Null when not loaded.",
    )

    class Config:
        from_attributes = True
        populate_by_name = True
