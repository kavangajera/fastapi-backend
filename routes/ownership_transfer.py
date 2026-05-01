from fastapi import Depends, Path

from database import get_db
from middlewares.auth import auth_incoming_req
from schemas.ownership_transfer_input import (
    OwnershipTransferOtpRequestInput,
    OwnershipTransferCreateInput,
    OwnershipTransferAcceptInput,
)
from schemas.response_schema import Response_Schema
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services import ownership_transfer


def success_response(data, message="Success", status_code=200):
    return Response_Schema(status_code=status_code, message=message, data=data)


def request_transfer_otp(
    payload: OwnershipTransferOtpRequestInput,
    db=Depends(get_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = ownership_transfer.request_create_transfer_otp(payload, db, user)
    return success_response(res, "OTP sent successfully")


def create_transfer_request(
    payload: OwnershipTransferCreateInput,
    db=Depends(get_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = ownership_transfer.create_transfer_request(payload, db, user)
    return success_response(res, "Transfer request created successfully", 201)


def send_accept_otp(
    transfer_id: int = Path(
        ...,
        description="Ownership transfer request ID.",
        examples=[12],
    ),
    db=Depends(get_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = ownership_transfer.send_accept_otp(transfer_id, db, user)
    return success_response(res, "OTP sent successfully")


def accept_transfer_request(
    transfer_id: int = Path(
        ...,
        description="Ownership transfer request ID.",
        examples=[12],
    ),
    payload: OwnershipTransferAcceptInput = ...,
    db=Depends(get_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = ownership_transfer.accept_transfer_request(transfer_id, payload, db, user)
    return success_response(res, "Transfer request accepted successfully")


def reject_transfer_request(
    transfer_id: int = Path(
        ...,
        description="Ownership transfer request ID.",
        examples=[12],
    ),
    db=Depends(get_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = ownership_transfer.reject_transfer_request(transfer_id, db, user)
    return success_response(res, "Transfer request rejected successfully")


def get_transfer_request(
    transfer_id: int = Path(
        ...,
        description="Ownership transfer request ID.",
        examples=[12],
    ),
    db=Depends(get_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = ownership_transfer.get_transfer_request(transfer_id, db, user)
    return success_response(res, "Transfer request retrieved successfully")
