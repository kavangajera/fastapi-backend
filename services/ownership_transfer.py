from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.config import settings
from core.enums import OtpPurpose, OwnershipTransferStatus, UserRole
from models.ownership_transfer import OwnershipTransferRequest
from models.pharmacy import Pharmacy
from models.user import User
from schemas.ownership_transfer_input import (
    OwnershipTransferCreateInput,
    OwnershipTransferOtpRequestInput,
    OwnershipTransferAcceptInput,
)
from schemas.ownership_transfer_output import OwnershipTransferOutput
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services import otp_service


def _raise_error(status_code: int, message: str):
    """Raise HTTPException with Response_Schema format in detail."""
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
    )


def _now() -> datetime:
    return datetime.utcnow()


def _to_transfer_output(transfer_db: OwnershipTransferRequest) -> dict:
    return OwnershipTransferOutput.model_validate(transfer_db).model_dump(by_alias=False)


def _get_transfer_or_404(db: Session, transfer_id: int) -> OwnershipTransferRequest:
    transfer = db.query(OwnershipTransferRequest).filter(
        OwnershipTransferRequest.transfer_id == transfer_id
    ).first()
    if not transfer:
        _raise_error(404, "Transfer request not found")
    return transfer


def _expire_if_needed(db: Session, transfer: OwnershipTransferRequest) -> OwnershipTransferRequest:
    if (
        transfer.status == OwnershipTransferStatus.ACTIVE
        and transfer.expires_at <= _now()
    ):
        transfer.status = OwnershipTransferStatus.EXPIRED
        try:
            db.commit()
            db.refresh(transfer)
        except SQLAlchemyError:
            db.rollback()
            _raise_error(500, "Failed to update transfer status")
    return transfer


def _ensure_owner(user: System_Internal_User_Schema):
    if user.role != UserRole.PHARMACY_OWNER:
        _raise_error(403, "Only pharmacy owners can perform this action")


def _ensure_active_transfer(
    db: Session, transfer: OwnershipTransferRequest
) -> OwnershipTransferRequest:
    transfer = _expire_if_needed(db, transfer)
    if transfer.status != OwnershipTransferStatus.ACTIVE:
        _raise_error(400, f"Transfer request is {transfer.status.value}")
    return transfer


def _ensure_no_active_transfer(db: Session, pharmacy_id: int):
    existing = db.query(OwnershipTransferRequest).filter(
        OwnershipTransferRequest.pharmacy_id == pharmacy_id,
        OwnershipTransferRequest.status == OwnershipTransferStatus.ACTIVE,
    ).first()
    if not existing:
        return
    existing = _expire_if_needed(db, existing)
    if existing.status == OwnershipTransferStatus.ACTIVE:
        _raise_error(409, "An active transfer request already exists for this pharmacy")


def request_create_transfer_otp(
    payload: OwnershipTransferOtpRequestInput,
    db: Session,
    user: System_Internal_User_Schema,
):
    _ensure_owner(user)

    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.pharmacy_id == payload.pharmacy_id
    ).first()
    if not pharmacy:
        _raise_error(404, "Pharmacy not found")
    if pharmacy.user_id != user.user_id:
        _raise_error(403, "You can only transfer pharmacies you own")

    if payload.new_owner_id == user.user_id:
        _raise_error(400, "New owner must be different from current owner")

    new_owner = db.query(User).filter(User.user_id == payload.new_owner_id).first()
    if not new_owner:
        _raise_error(404, "New owner not found")
    if new_owner.role != UserRole.PHARMACY_OWNER:
        _raise_error(400, "New owner must be a pharmacy owner")

    _ensure_no_active_transfer(db, pharmacy.pharmacy_id)

    current_owner = db.query(User).filter(User.user_id == user.user_id).first()
    if not current_owner:
        _raise_error(404, "Current owner not found")

    otp_service.issue_otp(
        db=db,
        user_id=current_owner.user_id,
        email=current_owner.email,
        purpose=OtpPurpose.TRANSFER_CREATE,
        pharmacy_id=payload.pharmacy_id,
        new_owner_id=payload.new_owner_id,
    )
    return None


def create_transfer_request(
    payload: OwnershipTransferCreateInput,
    db: Session,
    user: System_Internal_User_Schema,
):
    _ensure_owner(user)

    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.pharmacy_id == payload.pharmacy_id
    ).first()
    if not pharmacy:
        _raise_error(404, "Pharmacy not found")
    if pharmacy.user_id != user.user_id:
        _raise_error(403, "You can only transfer pharmacies you own")

    if payload.new_owner_id == user.user_id:
        _raise_error(400, "New owner must be different from current owner")

    new_owner = db.query(User).filter(User.user_id == payload.new_owner_id).first()
    if not new_owner:
        _raise_error(404, "New owner not found")
    if new_owner.role != UserRole.PHARMACY_OWNER:
        _raise_error(400, "New owner must be a pharmacy owner")

    _ensure_no_active_transfer(db, pharmacy.pharmacy_id)

    otp_service.verify_otp(
        db=db,
        user_id=user.user_id,
        purpose=OtpPurpose.TRANSFER_CREATE,
        otp_code=payload.otp_code,
        pharmacy_id=payload.pharmacy_id,
        new_owner_id=payload.new_owner_id,
    )

    expires_at = _now() + timedelta(minutes=settings.TRANSFER_REQUEST_TTL_MINUTES)
    transfer = OwnershipTransferRequest(
        pharmacy_id=payload.pharmacy_id,
        current_owner_id=user.user_id,
        new_owner_id=payload.new_owner_id,
        status=OwnershipTransferStatus.ACTIVE,
        expires_at=expires_at,
    )

    try:
        db.add(transfer)
        db.commit()
        db.refresh(transfer)
    except SQLAlchemyError:
        db.rollback()
        _raise_error(500, "Failed to create transfer request")

    return _to_transfer_output(transfer)


def send_accept_otp(
    transfer_id: int,
    db: Session,
    user: System_Internal_User_Schema,
):
    transfer = _get_transfer_or_404(db, transfer_id)
    transfer = _ensure_active_transfer(db, transfer)

    if transfer.new_owner_id != user.user_id:
        _raise_error(403, "Only the new owner can accept this transfer")

    new_owner = db.query(User).filter(User.user_id == user.user_id).first()
    if not new_owner:
        _raise_error(404, "New owner not found")

    otp_service.issue_otp(
        db=db,
        user_id=new_owner.user_id,
        email=new_owner.email,
        purpose=OtpPurpose.TRANSFER_ACCEPT,
        transfer_request_id=transfer.transfer_id,
        pharmacy_id=transfer.pharmacy_id,
        new_owner_id=transfer.new_owner_id,
    )
    return None


def accept_transfer_request(
    transfer_id: int,
    payload: OwnershipTransferAcceptInput,
    db: Session,
    user: System_Internal_User_Schema,
):
    transfer = _get_transfer_or_404(db, transfer_id)
    transfer = _ensure_active_transfer(db, transfer)

    if transfer.new_owner_id != user.user_id:
        _raise_error(403, "Only the new owner can accept this transfer")

    otp_service.verify_otp(
        db=db,
        user_id=user.user_id,
        purpose=OtpPurpose.TRANSFER_ACCEPT,
        otp_code=payload.otp_code,
        transfer_request_id=transfer.transfer_id,
        pharmacy_id=transfer.pharmacy_id,
        new_owner_id=transfer.new_owner_id,
    )

    pharmacy = db.query(Pharmacy).filter(
        Pharmacy.pharmacy_id == transfer.pharmacy_id
    ).first()
    if not pharmacy:
        _raise_error(404, "Pharmacy not found")
    if pharmacy.user_id != transfer.current_owner_id:
        _raise_error(409, "Pharmacy ownership has already changed")

    pharmacy.user_id = transfer.new_owner_id
    transfer.status = OwnershipTransferStatus.ACCEPTED
    transfer.accepted_at = _now()

    try:
        db.commit()
        db.refresh(transfer)
    except SQLAlchemyError:
        db.rollback()
        _raise_error(500, "Failed to accept transfer request")

    return _to_transfer_output(transfer)


def reject_transfer_request(
    transfer_id: int,
    db: Session,
    user: System_Internal_User_Schema,
):
    transfer = _get_transfer_or_404(db, transfer_id)
    transfer = _ensure_active_transfer(db, transfer)

    if transfer.new_owner_id != user.user_id:
        _raise_error(403, "Only the new owner can reject this transfer")

    transfer.status = OwnershipTransferStatus.REJECTED
    transfer.rejected_at = _now()

    try:
        db.commit()
        db.refresh(transfer)
    except SQLAlchemyError:
        db.rollback()
        _raise_error(500, "Failed to reject transfer request")

    return _to_transfer_output(transfer)


def get_transfer_request(
    transfer_id: int,
    db: Session,
    user: System_Internal_User_Schema,
):
    transfer = _get_transfer_or_404(db, transfer_id)

    if user.role != UserRole.ADMIN and user.user_id not in (
        transfer.current_owner_id,
        transfer.new_owner_id,
    ):
        _raise_error(403, "You do not have access to this transfer request")

    transfer = _expire_if_needed(db, transfer)
    return _to_transfer_output(transfer)
