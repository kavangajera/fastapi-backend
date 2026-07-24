"""
services/ownership_transfer_service.py
──────────────────────────────────────
Hand a pharmacy over from its current owner to another Queue RX user.

The flow is double-confirmed — both sides prove control of their mailbox
before anything moves:

    current owner                          new owner
    ─────────────                          ─────────
    POST .../initiate      → code by email
    POST .../create        (code)          → notified by email
                                           GET  .../incoming     (inbox)
                                           POST .../{id}/send-otp → code by email
                                           POST .../{id}/accept  (code)  ✓ moved
                                           POST .../{id}/reject          ✗
    POST .../{id}/cancel   (any time while pending)

The ownership move itself is one field — ``Pharmacy.user_id`` — flipped
inside the accept transaction, immediately after re-checking that the
pharmacy is *still* owned by the requester. That re-check is what makes the
flow safe against two overlapping transfers or an ownership change made by
some other route while the request sat pending.

Everything the pharmacy owns (subscription, inventory, reports, staff)
hangs off ``medical_store_id``, not off the owner, so it all follows the
pharmacy automatically. Technicians keep their assignment.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.enums import OtpPurpose, OwnershipTransferStatus, UserRole
from models.ownership_transfer import OwnershipTransferRequest
from models.pharmacy import Pharmacy
from models.user import User
from schemas.ownership_transfer_schemas import (
    TransferAcceptInput,
    TransferCreateInput,
    TransferInitiateInput,
    TransferOutput,
    TransferRejectInput,
)
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services import email_service, otp_service


def _raise_error(status_code: int, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
    )


def _now() -> datetime:
    return datetime.utcnow()


# ================= SERIALIZATION =================


def _serialize(transfer: OwnershipTransferRequest) -> dict:
    pharmacy = transfer.pharmacy
    current_owner = transfer.current_owner
    new_owner = transfer.new_owner

    payload = TransferOutput(
        transfer_id=transfer.transfer_id,
        medical_store_id=transfer.medical_store_id,
        pharmacy_name=pharmacy.name if pharmacy else None,
        current_owner_id=transfer.current_owner_id,
        current_owner_name=current_owner.username if current_owner else None,
        current_owner_email=current_owner.email if current_owner else None,
        new_owner_id=transfer.new_owner_id,
        new_owner_name=new_owner.username if new_owner else None,
        new_owner_email=new_owner.email if new_owner else None,
        status=transfer.status,
        message=transfer.message,
        created_at=transfer.created_at,
        expires_at=transfer.expires_at,
        accepted_at=transfer.accepted_at,
        rejected_at=transfer.rejected_at,
        cancelled_at=transfer.cancelled_at,
        is_actionable=(
            transfer.status == OwnershipTransferStatus.PENDING.value
            and transfer.expires_at > _now()
        ),
    )
    return payload.model_dump(by_alias=False)


# ================= INTERNAL HELPERS =================


def _ensure_owner(user: System_Internal_User_Schema) -> None:
    if user.role != UserRole.PHARMACY_OWNER:
        _raise_error(403, "Only pharmacy owners can transfer a pharmacy")


async def _get_transfer_or_404(
    db: AsyncSession, transfer_id: int
) -> OwnershipTransferRequest:
    result = await db.execute(
        select(OwnershipTransferRequest).where(
            OwnershipTransferRequest.transfer_id == transfer_id
        )
    )
    transfer = result.scalar_one_or_none()
    if transfer is None:
        _raise_error(404, "Transfer request not found")
    return transfer


async def _expire_if_needed(
    db: AsyncSession, transfer: OwnershipTransferRequest
) -> OwnershipTransferRequest:
    """Lazily flip a stale PENDING request to EXPIRED. No sweeper needed."""
    if (
        transfer.status == OwnershipTransferStatus.PENDING.value
        and transfer.expires_at <= _now()
    ):
        transfer.status = OwnershipTransferStatus.EXPIRED.value
        try:
            await db.commit()
            await db.refresh(transfer)
        except SQLAlchemyError as exc:
            await db.rollback()
            logger.error("Failed to expire transfer request: {err}", err=str(exc))
    return transfer


async def _ensure_pending(
    db: AsyncSession, transfer: OwnershipTransferRequest
) -> OwnershipTransferRequest:
    transfer = await _expire_if_needed(db, transfer)
    if transfer.status != OwnershipTransferStatus.PENDING.value:
        _raise_error(
            400, f"This transfer request is no longer active (status: {transfer.status})"
        )
    return transfer


async def _get_owned_pharmacy(
    db: AsyncSession, medical_store_id: int, owner_id: int
) -> Pharmacy:
    result = await db.execute(
        select(Pharmacy).where(Pharmacy.medical_store_id == medical_store_id)
    )
    pharmacy = result.scalar_one_or_none()
    if pharmacy is None:
        _raise_error(404, "Pharmacy not found")
    if pharmacy.user_id != owner_id:
        _raise_error(403, "You can only transfer a pharmacy you own")
    return pharmacy


async def _resolve_new_owner(
    db: AsyncSession, payload: TransferInitiateInput, current_owner_id: int
) -> User:
    """Look the recipient up by email or id, and check they can receive."""
    if payload.new_owner_email is None and payload.new_owner_id is None:
        _raise_error(400, "Provide either new_owner_email or new_owner_id")

    stmt = select(User)
    if payload.new_owner_email is not None:
        stmt = stmt.where(User.email == payload.new_owner_email.strip().lower())
    else:
        stmt = stmt.where(User.user_id == payload.new_owner_id)

    new_owner = (await db.execute(stmt)).scalar_one_or_none()
    if new_owner is None:
        _raise_error(
            404,
            "No Queue RX account found for that user. They must sign up before "
            "ownership can be transferred to them.",
        )
    if new_owner.user_id == current_owner_id:
        _raise_error(400, "You cannot transfer a pharmacy to yourself")
    if new_owner.IsActive != 1:
        _raise_error(400, "That account is deactivated and cannot receive a pharmacy")
    if new_owner.role != UserRole.PHARMACY_OWNER:
        _raise_error(
            400,
            "The new owner must hold a pharmacy-owner account. Technician and admin "
            "accounts cannot own a pharmacy.",
        )
    return new_owner


async def _ensure_no_pending_transfer(db: AsyncSession, medical_store_id: int) -> None:
    result = await db.execute(
        select(OwnershipTransferRequest).where(
            OwnershipTransferRequest.medical_store_id == medical_store_id,
            OwnershipTransferRequest.status == OwnershipTransferStatus.PENDING.value,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is None:
        return
    existing = await _expire_if_needed(db, existing)
    if existing.status == OwnershipTransferStatus.PENDING.value:
        _raise_error(
            409,
            f"A transfer request for this pharmacy is already pending "
            f"(transfer_id {existing.transfer_id}). Cancel it before starting another.",
        )


async def _get_user(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        _raise_error(404, "User not found")
    return user


# ================= CURRENT OWNER — OPEN A TRANSFER =================


async def initiate_transfer(
    payload: TransferInitiateInput,
    db: AsyncSession,
    user: System_Internal_User_Schema,
) -> dict:
    """Step 1 — validate everything, then mail a code to the current owner."""
    _ensure_owner(user)

    pharmacy = await _get_owned_pharmacy(db, payload.medical_store_id, user.user_id)
    new_owner = await _resolve_new_owner(db, payload, user.user_id)
    await _ensure_no_pending_transfer(db, pharmacy.medical_store_id)

    current_owner = await _get_user(db, user.user_id)

    await otp_service.issue_otp(
        db,
        user_id=current_owner.user_id,
        email=current_owner.email,
        purpose=OtpPurpose.TRANSFER_CREATE,
        purpose_line=(
            f"You are about to transfer ownership of \"{pharmacy.name}\" to "
            f"{new_owner.username} ({new_owner.email})."
        ),
        medical_store_id=pharmacy.medical_store_id,
        new_owner_id=new_owner.user_id,
    )

    return {
        "otp_sent": True,
        "sent_to": current_owner.email,
        "medical_store_id": pharmacy.medical_store_id,
        "pharmacy_name": pharmacy.name,
        "new_owner_id": new_owner.user_id,
        "new_owner_email": new_owner.email,
        "expires_in_minutes": max(1, round(settings.OTP_TTL_SECONDS / 60)),
    }


async def create_transfer(
    payload: TransferCreateInput,
    db: AsyncSession,
    user: System_Internal_User_Schema,
) -> dict:
    """Step 2 — verify the owner's code and open the pending request."""
    _ensure_owner(user)

    pharmacy = await _get_owned_pharmacy(db, payload.medical_store_id, user.user_id)
    new_owner = await _resolve_new_owner(db, payload, user.user_id)
    await _ensure_no_pending_transfer(db, pharmacy.medical_store_id)

    await otp_service.verify_otp(
        db,
        user_id=user.user_id,
        purpose=OtpPurpose.TRANSFER_CREATE,
        code=payload.otp_code,
        medical_store_id=pharmacy.medical_store_id,
        new_owner_id=new_owner.user_id,
    )

    current_owner = await _get_user(db, user.user_id)
    transfer = OwnershipTransferRequest(
        medical_store_id=pharmacy.medical_store_id,
        current_owner_id=current_owner.user_id,
        new_owner_id=new_owner.user_id,
        status=OwnershipTransferStatus.PENDING.value,
        message=payload.message,
        expires_at=_now() + timedelta(hours=settings.TRANSFER_REQUEST_TTL_HOURS),
    )

    try:
        db.add(transfer)
        await db.commit()
        await db.refresh(transfer)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Database error creating transfer request: {err}", err=str(exc))
        _raise_error(500, "Failed to create transfer request")

    # Notify the recipient. Advisory only — the request is already committed
    # and visible in their inbox, so a mail failure must not undo it.
    text, html = email_service.transfer_request_email(
        pharmacy_name=pharmacy.name,
        current_owner_name=current_owner.username,
        current_owner_email=current_owner.email,
        expires_at_str=transfer.expires_at.strftime("%Y-%m-%d %H:%M"),
    )
    await email_service.send_email(
        new_owner.email,
        f"You have been offered ownership of {pharmacy.name}",
        text,
        html=html,
        raise_on_failure=False,
    )

    logger.info(
        "Ownership transfer {tid} opened: store={sid} {frm} → {to}",
        tid=transfer.transfer_id,
        sid=pharmacy.medical_store_id,
        frm=current_owner.user_id,
        to=new_owner.user_id,
    )
    return _serialize(transfer)


async def cancel_transfer(
    transfer_id: int,
    db: AsyncSession,
    user: System_Internal_User_Schema,
) -> dict:
    """Current owner withdraws a request the recipient has not answered."""
    transfer = await _get_transfer_or_404(db, transfer_id)
    transfer = await _ensure_pending(db, transfer)

    if transfer.current_owner_id != user.user_id and user.role != UserRole.ADMIN:
        _raise_error(403, "Only the current owner can cancel this transfer request")

    transfer.status = OwnershipTransferStatus.CANCELLED.value
    transfer.cancelled_at = _now()

    try:
        await db.commit()
        await db.refresh(transfer)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Database error cancelling transfer: {err}", err=str(exc))
        _raise_error(500, "Failed to cancel transfer request")

    return _serialize(transfer)


# ================= NEW OWNER — THE RECEIVING SIDE =================


async def list_incoming_transfers(
    db: AsyncSession,
    user: System_Internal_User_Schema,
    pending_only: bool = True,
) -> list[dict]:
    """The recipient's inbox: pharmacies being offered *to* this user.

    This is the endpoint the receiving side polls — it is what surfaces the
    "you have been asked to become owner" prompt in the app.
    """
    stmt = select(OwnershipTransferRequest).where(
        OwnershipTransferRequest.new_owner_id == user.user_id
    )
    if pending_only:
        stmt = stmt.where(
            OwnershipTransferRequest.status == OwnershipTransferStatus.PENDING.value
        )
    stmt = stmt.order_by(OwnershipTransferRequest.transfer_id.desc())

    rows = (await db.execute(stmt)).scalars().all()

    out: list[dict] = []
    for row in rows:
        row = await _expire_if_needed(db, row)
        if pending_only and row.status != OwnershipTransferStatus.PENDING.value:
            continue  # expired while we were reading it
        out.append(_serialize(row))
    return out


async def list_outgoing_transfers(
    db: AsyncSession,
    user: System_Internal_User_Schema,
    pending_only: bool = False,
) -> list[dict]:
    """Requests this user has opened on pharmacies they own."""
    stmt = select(OwnershipTransferRequest).where(
        OwnershipTransferRequest.current_owner_id == user.user_id
    )
    if pending_only:
        stmt = stmt.where(
            OwnershipTransferRequest.status == OwnershipTransferStatus.PENDING.value
        )
    stmt = stmt.order_by(OwnershipTransferRequest.transfer_id.desc())

    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize(await _expire_if_needed(db, row)) for row in rows]


async def send_accept_otp(
    transfer_id: int,
    db: AsyncSession,
    user: System_Internal_User_Schema,
) -> dict:
    """Recipient asks for the code that lets them accept."""
    transfer = await _get_transfer_or_404(db, transfer_id)
    transfer = await _ensure_pending(db, transfer)

    if transfer.new_owner_id != user.user_id:
        _raise_error(403, "Only the prospective new owner can accept this transfer")

    new_owner = await _get_user(db, user.user_id)
    pharmacy = transfer.pharmacy

    await otp_service.issue_otp(
        db,
        user_id=new_owner.user_id,
        email=new_owner.email,
        purpose=OtpPurpose.TRANSFER_ACCEPT,
        purpose_line=(
            f"You are about to accept ownership of "
            f"\"{pharmacy.name if pharmacy else 'a pharmacy'}\" on Queue RX."
        ),
        medical_store_id=transfer.medical_store_id,
        transfer_id=transfer.transfer_id,
        new_owner_id=new_owner.user_id,
    )

    return {
        "otp_sent": True,
        "sent_to": new_owner.email,
        "transfer_id": transfer.transfer_id,
        "expires_in_minutes": max(1, round(settings.OTP_TTL_SECONDS / 60)),
    }


async def accept_transfer(
    transfer_id: int,
    payload: TransferAcceptInput,
    db: AsyncSession,
    user: System_Internal_User_Schema,
) -> dict:
    """Recipient confirms — ownership actually moves here."""
    transfer = await _get_transfer_or_404(db, transfer_id)
    transfer = await _ensure_pending(db, transfer)

    if transfer.new_owner_id != user.user_id:
        _raise_error(403, "Only the prospective new owner can accept this transfer")

    await otp_service.verify_otp(
        db,
        user_id=user.user_id,
        purpose=OtpPurpose.TRANSFER_ACCEPT,
        code=payload.otp_code,
        medical_store_id=transfer.medical_store_id,
        transfer_id=transfer.transfer_id,
        new_owner_id=user.user_id,
    )

    result = await db.execute(
        select(Pharmacy).where(Pharmacy.medical_store_id == transfer.medical_store_id)
    )
    pharmacy = result.scalar_one_or_none()
    if pharmacy is None:
        _raise_error(404, "Pharmacy not found")

    # Guard against the pharmacy having changed hands while this request sat
    # pending — the transfer is only valid from the owner who opened it.
    if pharmacy.user_id != transfer.current_owner_id:
        transfer.status = OwnershipTransferStatus.CANCELLED.value
        transfer.cancelled_at = _now()
        try:
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
        _raise_error(409, "This pharmacy has already changed ownership")

    previous_owner = await _get_user(db, transfer.current_owner_id)

    pharmacy.user_id = transfer.new_owner_id
    transfer.status = OwnershipTransferStatus.ACCEPTED.value
    transfer.accepted_at = _now()

    try:
        await db.commit()
        await db.refresh(transfer)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Database error accepting transfer: {err}", err=str(exc))
        _raise_error(500, "Failed to accept transfer request")

    new_owner = await _get_user(db, user.user_id)
    text, html = email_service.transfer_outcome_email(
        pharmacy_name=pharmacy.name, new_owner_name=new_owner.username, accepted=True
    )
    await email_service.send_email(
        previous_owner.email,
        f"Ownership of {pharmacy.name} has been transferred",
        text,
        html=html,
        raise_on_failure=False,
    )

    logger.info(
        "Ownership transfer {tid} ACCEPTED: store={sid} now owned by {uid}",
        tid=transfer.transfer_id,
        sid=pharmacy.medical_store_id,
        uid=transfer.new_owner_id,
    )
    return _serialize(transfer)


async def reject_transfer(
    transfer_id: int,
    payload: TransferRejectInput | None,
    db: AsyncSession,
    user: System_Internal_User_Schema,
) -> dict:
    """Recipient declines. No OTP — declining cannot cause harm."""
    transfer = await _get_transfer_or_404(db, transfer_id)
    transfer = await _ensure_pending(db, transfer)

    if transfer.new_owner_id != user.user_id:
        _raise_error(403, "Only the prospective new owner can decline this transfer")

    transfer.status = OwnershipTransferStatus.REJECTED.value
    transfer.rejected_at = _now()
    if payload is not None and payload.reason:
        transfer.message = payload.reason

    try:
        await db.commit()
        await db.refresh(transfer)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Database error rejecting transfer: {err}", err=str(exc))
        _raise_error(500, "Failed to decline transfer request")

    previous_owner = await _get_user(db, transfer.current_owner_id)
    new_owner = await _get_user(db, user.user_id)
    pharmacy = transfer.pharmacy
    text, html = email_service.transfer_outcome_email(
        pharmacy_name=pharmacy.name if pharmacy else "your pharmacy",
        new_owner_name=new_owner.username,
        accepted=False,
    )
    await email_service.send_email(
        previous_owner.email,
        "Your ownership transfer request was declined",
        text,
        html=html,
        raise_on_failure=False,
    )

    return _serialize(transfer)


# ================= EITHER PARTY =================


async def get_transfer(
    transfer_id: int,
    db: AsyncSession,
    user: System_Internal_User_Schema,
) -> dict:
    transfer = await _get_transfer_or_404(db, transfer_id)

    if user.role != UserRole.ADMIN and user.user_id not in (
        transfer.current_owner_id,
        transfer.new_owner_id,
    ):
        _raise_error(403, "You do not have access to this transfer request")

    transfer = await _expire_if_needed(db, transfer)
    return _serialize(transfer)


async def list_my_transfers(
    db: AsyncSession,
    user: System_Internal_User_Schema,
) -> dict:
    """Both directions in one call — convenient for a single settings screen."""
    stmt = (
        select(OwnershipTransferRequest)
        .where(
            or_(
                OwnershipTransferRequest.current_owner_id == user.user_id,
                OwnershipTransferRequest.new_owner_id == user.user_id,
            )
        )
        .order_by(OwnershipTransferRequest.transfer_id.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()

    incoming: list[dict] = []
    outgoing: list[dict] = []
    for row in rows:
        row = await _expire_if_needed(db, row)
        data = _serialize(row)
        if row.new_owner_id == user.user_id:
            incoming.append(data)
        else:
            outgoing.append(data)

    return {
        "incoming": incoming,
        "outgoing": outgoing,
        "pending_incoming_count": sum(1 for t in incoming if t["is_actionable"]),
    }
