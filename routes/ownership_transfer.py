"""
routes/ownership_transfer.py
────────────────────────────
Pharmacy ownership transfer — both sides of the hand-over.

Sender side (current owner):
    POST   /pharmacy/ownership-transfer/initiate      → OTP to current owner
    POST   /pharmacy/ownership-transfer/create        → open the request
    POST   /pharmacy/ownership-transfer/{id}/cancel   → withdraw it
    GET    /pharmacy/ownership-transfer/outgoing      → requests I opened

Receiving side (prospective new owner):
    GET    /pharmacy/ownership-transfer/incoming      → my inbox  ⟵ poll this
    POST   /pharmacy/ownership-transfer/{id}/send-otp → OTP to me
    POST   /pharmacy/ownership-transfer/{id}/accept   → take ownership
    POST   /pharmacy/ownership-transfer/{id}/reject   → decline

Shared:
    GET    /pharmacy/ownership-transfer/my            → both lists + badge count
    GET    /pharmacy/ownership-transfer/{id}          → one request

All routes require a Bearer token. The literal-path routes are declared
before `/{transfer_id}` so "incoming" is never parsed as an id.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from middlewares.auth import auth_incoming_req
from schemas.ownership_transfer_schemas import (
    TransferAcceptInput,
    TransferCreateInput,
    TransferInitiateInput,
    TransferRejectInput,
)
from schemas.response_schema import Response_Schema, success_response
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services import ownership_transfer_service as service

router = APIRouter(prefix="/pharmacy/ownership-transfer", tags=["Ownership Transfer"])


# ================= CURRENT OWNER =================


@router.post(
    "/initiate",
    response_model=Response_Schema,
    summary="Step 1 — send yourself a code to start a transfer",
    description=(
        "Validates that you own the pharmacy and that the recipient can receive it, "
        "then emails a **6-digit code to your own address**.\n\n"
        "Identify the recipient by `new_owner_email` (recommended) or `new_owner_id`. "
        "They must already have a pharmacy-owner account on Queue RX.\n\n"
        "🔒 Requires Bearer token. Owner only."
    ),
)
async def initiate_transfer(
    body: TransferInitiateInput,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = await service.initiate_transfer(body, db, user)
    return success_response(res, "Verification code sent to your email")


@router.post(
    "/create",
    response_model=Response_Schema,
    summary="Step 2 — confirm the code and open the transfer request",
    description=(
        "Verifies the code from `/initiate` and creates the **pending** request. "
        "The recipient is emailed and the request appears in their "
        "`GET /pharmacy/ownership-transfer/incoming` inbox.\n\n"
        "Ownership does **not** move yet — the recipient must accept.\n\n"
        "🔒 Requires Bearer token. Owner only."
    ),
)
async def create_transfer(
    body: TransferCreateInput,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = await service.create_transfer(body, db, user)
    return success_response(res, "Transfer request sent to the new owner", 201)


@router.get(
    "/outgoing",
    response_model=Response_Schema,
    summary="Transfer requests you have opened",
    description="Requests where **you are the current owner**. 🔒 Requires Bearer token.",
)
async def list_outgoing(
    pending_only: bool = Query(False, description="Return only still-actionable requests."),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = await service.list_outgoing_transfers(db, user, pending_only=pending_only)
    return success_response(res, "Outgoing transfer requests retrieved successfully")


# ================= RECEIVING SIDE =================


@router.get(
    "/incoming",
    response_model=Response_Schema,
    summary="Your inbox — pharmacies being offered to you",
    description=(
        "Requests where **you are the prospective new owner**. This is the endpoint "
        "the receiving side polls to show the *\"someone wants to make you the owner "
        "of X\"* prompt.\n\n"
        "Each item carries `is_actionable` (pending and not expired), the pharmacy "
        "name, the current owner's name/email, an optional `message`, and "
        "`expires_at`. Stale requests are marked `EXPIRED` on read.\n\n"
        "Defaults to pending only — pass `pending_only=false` for full history.\n\n"
        "🔒 Requires Bearer token."
    ),
)
async def list_incoming(
    pending_only: bool = Query(True, description="Return only still-actionable requests."),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = await service.list_incoming_transfers(db, user, pending_only=pending_only)
    return success_response(
        res,
        f"{len(res)} incoming transfer request(s) retrieved successfully",
    )


@router.get(
    "/my",
    response_model=Response_Schema,
    summary="Both directions plus an unread-style badge count",
    description=(
        "Returns `{incoming, outgoing, pending_incoming_count}` in one call — handy "
        "for a settings screen or a notification badge.\n\n"
        "🔒 Requires Bearer token."
    ),
)
async def list_my_transfers(
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = await service.list_my_transfers(db, user)
    return success_response(res, "Transfer requests retrieved successfully")


@router.post(
    "/{transfer_id}/send-otp",
    response_model=Response_Schema,
    summary="Send yourself the code needed to accept",
    description=(
        "Emails a **6-digit code to the prospective new owner's address**. Call this "
        "before `/accept`. Only the named recipient may call it.\n\n"
        "🔒 Requires Bearer token."
    ),
)
async def send_accept_otp(
    transfer_id: int = Path(..., description="Transfer request ID.", examples=[12]),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = await service.send_accept_otp(transfer_id, db, user)
    return success_response(res, "Verification code sent to your email")


@router.post(
    "/{transfer_id}/accept",
    response_model=Response_Schema,
    summary="Accept — take ownership of the pharmacy",
    description=(
        "Verifies the code from `/send-otp` and **moves ownership to you**. "
        "Everything attached to the pharmacy — subscription, inventory, reports, "
        "technicians — follows it; the previous owner loses owner access and is "
        "emailed the outcome.\n\n"
        "Returns `409` if the pharmacy changed hands while the request was pending.\n\n"
        "🔒 Requires Bearer token. Recipient only."
    ),
)
async def accept_transfer(
    transfer_id: int = Path(..., description="Transfer request ID.", examples=[12]),
    body: TransferAcceptInput = ...,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = await service.accept_transfer(transfer_id, body, db, user)
    return success_response(res, "Ownership transferred successfully")


@router.post(
    "/{transfer_id}/reject",
    response_model=Response_Schema,
    summary="Decline the transfer",
    description=(
        "Declines the request. **No code required** — declining changes nothing that "
        "needs protecting. The current owner is emailed and keeps the pharmacy.\n\n"
        "🔒 Requires Bearer token. Recipient only."
    ),
)
async def reject_transfer(
    transfer_id: int = Path(..., description="Transfer request ID.", examples=[12]),
    body: TransferRejectInput | None = Body(None),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = await service.reject_transfer(transfer_id, body, db, user)
    return success_response(res, "Transfer request declined")


@router.post(
    "/{transfer_id}/cancel",
    response_model=Response_Schema,
    summary="Withdraw a request you opened",
    description=(
        "Cancels a still-pending request. Only the current owner (or an admin) may "
        "call it.\n\n🔒 Requires Bearer token."
    ),
)
async def cancel_transfer(
    transfer_id: int = Path(..., description="Transfer request ID.", examples=[12]),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = await service.cancel_transfer(transfer_id, db, user)
    return success_response(res, "Transfer request cancelled")


@router.get(
    "/{transfer_id}",
    response_model=Response_Schema,
    summary="Get one transfer request",
    description=(
        "Readable by either party (or an admin). Flips a stale request to `EXPIRED` "
        "on read.\n\n🔒 Requires Bearer token."
    ),
)
async def get_transfer(
    transfer_id: int = Path(..., description="Transfer request ID.", examples=[12]),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    res = await service.get_transfer(transfer_id, db, user)
    return success_response(res, "Transfer request retrieved successfully")
