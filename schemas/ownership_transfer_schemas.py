"""
schemas/ownership_transfer_schemas.py
─────────────────────────────────────
Payloads and outputs for the pharmacy ownership-transfer flow.

Per the project's id-prefix convention, requests take ``medical_store_id``
while responses expose ``pharmacy_id`` (via ``validation_alias``), plus the
denormalized names/emails the UI needs so it does not have to fan out to
`/user/...` for every row in an inbox list.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.enums import OwnershipTransferStatus
from schemas.password_reset_schemas import normalize_email


# ================= INPUTS =================


class TransferInitiateInput(BaseModel):
    """Step 1 — current owner asks for a code to open a transfer.

    Identify the recipient by **either** `new_owner_email` or `new_owner_id`.
    Email is the friendlier option: owners rarely know another user's id.
    """

    medical_store_id: int = Field(
        ...,
        description="Pharmacy whose ownership should be transferred.",
        examples=[2],
    )
    new_owner_email: str | None = Field(
        None,
        description="Email of the user who should become the new owner.",
        examples=["newowner@pharmacy.com"],
    )
    new_owner_id: int | None = Field(
        None,
        description="User ID of the new owner. Alternative to `new_owner_email`.",
        examples=[7],
    )
    message: str | None = Field(
        None,
        max_length=500,
        description="Optional note shown to the recipient.",
        examples=["Handing over the downtown branch as discussed."],
    )

    @field_validator("new_owner_email")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        return None if value is None else normalize_email(value)


class TransferCreateInput(TransferInitiateInput):
    """Step 2 — confirm with the code mailed to the current owner."""

    otp_code: str = Field(
        ...,
        min_length=4,
        max_length=10,
        description="Code emailed to the current owner.",
        examples=["482913"],
    )


class TransferAcceptInput(BaseModel):
    """Recipient confirms acceptance with the code mailed to them."""

    otp_code: str = Field(
        ...,
        min_length=4,
        max_length=10,
        description="Code emailed to the new owner.",
        examples=["739201"],
    )


class TransferRejectInput(BaseModel):
    reason: str | None = Field(
        None,
        max_length=500,
        description="Optional reason shown to the current owner.",
        examples=["Not taking over this location."],
    )


# ================= OUTPUT =================


class TransferOutput(BaseModel):
    """One transfer request, as returned to either party."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    transfer_id: int = Field(..., description="Transfer request ID.", examples=[12])
    pharmacy_id: int = Field(
        ...,
        validation_alias="medical_store_id",
        description="Pharmacy being transferred.",
        examples=[2],
    )
    pharmacy_name: str | None = Field(
        None, description="Pharmacy name.", examples=["Downtown Pharmacy"]
    )

    current_owner_id: int = Field(..., description="Current owner's user ID.", examples=[4])
    current_owner_name: str | None = Field(None, examples=["owner"])
    current_owner_email: str | None = Field(None, examples=["owner@pharmacy.com"])

    new_owner_id: int = Field(..., description="Prospective new owner's user ID.", examples=[7])
    new_owner_name: str | None = Field(None, examples=["newowner"])
    new_owner_email: str | None = Field(None, examples=["newowner@pharmacy.com"])

    status: OwnershipTransferStatus = Field(..., examples=["PENDING"])
    message: str | None = Field(None, description="Note from the current owner.")

    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None
    rejected_at: datetime | None = None
    cancelled_at: datetime | None = None

    # Convenience flags so the client does not re-derive state from
    # status + expires_at on every render.
    is_actionable: bool = Field(
        False,
        description="True when the request is PENDING and not yet expired.",
    )
