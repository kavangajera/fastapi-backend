from pydantic import BaseModel, Field


class OwnershipTransferOtpRequestInput(BaseModel):
    """Request payload to send an OTP for creating a transfer request."""

    pharmacy_id: int = Field(
        ...,
        description="Pharmacy ID to transfer ownership.",
        examples=[2],
    )
    new_owner_id: int = Field(
        ...,
        description="User ID of the new owner.",
        examples=[7],
    )


class OwnershipTransferCreateInput(BaseModel):
    """Payload to create a transfer request after OTP verification."""

    pharmacy_id: int = Field(
        ...,
        description="Pharmacy ID to transfer ownership.",
        examples=[2],
    )
    new_owner_id: int = Field(
        ...,
        description="User ID of the new owner.",
        examples=[7],
    )
    otp_code: str = Field(
        ...,
        description="OTP code sent to the current owner.",
        examples=["482913"],
    )


class OwnershipTransferAcceptInput(BaseModel):
    """Payload to accept a transfer request after OTP verification."""

    otp_code: str = Field(
        ...,
        description="OTP code sent to the new owner.",
        examples=["739201"],
    )
