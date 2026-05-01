from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from core.enums import OwnershipTransferStatus


class OwnershipTransferOutput(BaseModel):
    """Frontend-facing ownership transfer output."""

    id: int = Field(
        ...,
        alias="transfer_id",
        description="Unique ownership transfer request ID.",
        examples=[12],
    )
    pharmacy_id: int = Field(
        ...,
        alias="pharmacy_id",
        description="Pharmacy ID being transferred.",
        examples=[2],
    )
    current_owner_id: int = Field(
        ...,
        alias="current_owner_id",
        description="User ID of the current owner.",
        examples=[4],
    )
    new_owner_id: int = Field(
        ...,
        alias="new_owner_id",
        description="User ID of the new owner.",
        examples=[7],
    )
    status: OwnershipTransferStatus = Field(
        ...,
        alias="status",
        description="Current transfer request status.",
        examples=["ACTIVE"],
    )
    created_at: datetime = Field(
        ...,
        alias="created_at",
        description="Timestamp when the request was created.",
    )
    expires_at: datetime = Field(
        ...,
        alias="expires_at",
        description="Timestamp when the request expires.",
    )
    accepted_at: Optional[datetime] = Field(
        None,
        alias="accepted_at",
        description="Timestamp when the request was accepted.",
    )
    rejected_at: Optional[datetime] = Field(
        None,
        alias="rejected_at",
        description="Timestamp when the request was rejected.",
    )

    class Config:
        from_attributes = True
        populate_by_name = True
