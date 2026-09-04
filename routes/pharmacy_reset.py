"""
routes/pharmacy_reset.py
─────────────────────────
`POST /pharmacy/{ph_id}/reset-data` — soft-delete all data for one
pharmacy. OWNER (own pharmacy only) or ADMIN. Deliberately does NOT reuse
`ensure_pharmacy_access` — that also allows TECHNICIAN, which this
destructive action must not.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import UserRole
from middlewares.auth import auth_incoming_req
from models.pharmacy import Pharmacy
from schemas.pharmacy_reset import ResetDataRequest, ResetDataResponse
from schemas.response_schema import Response_Schema, success_response
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.activity_service import log_activity
from services.data_reset_service import reset_pharmacy_data

router = APIRouter(tags=["Pharmacy"])


def _forbid(message: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"status_code": 403, "message": message, "data": None},
    )


@router.post(
    "/pharmacy/{ph_id}/reset-data",
    response_model=Response_Schema,
    summary="Delete (soft-delete) all data for a pharmacy — OWNER (own pharmacy) or ADMIN only",
    description=(
        "Soft-deletes every Document, DrugReport/Medicine/Dispense, Invoice/"
        "InvoiceLineItem/InvoiceSummary, and MedicineInventory row for this "
        "pharmacy. Irreversible from the API (rows stay in the DB but are "
        "excluded from every read). Requires `confirm: true`. Restricted to "
        "the pharmacy's own OWNER or an ADMIN — technicians cannot call this."
    ),
)
async def reset_pharmacy_data_endpoint(
    ph_id: int,
    body: ResetDataRequest,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
) -> Response_Schema:
    if not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status_code": 400,
                "message": "Set confirm=true to reset this pharmacy's data.",
                "data": None,
            },
        )

    if user.role == UserRole.ADMIN:
        pass
    elif user.role == UserRole.PHARMACY_OWNER:
        result = await db.execute(
            select(Pharmacy.medical_store_id).where(
                Pharmacy.medical_store_id == ph_id,
                Pharmacy.user_id == user.user_id,
            )
        )
        if result.scalar_one_or_none() is None:
            _forbid("You can only reset your own pharmacy's data.")
    else:
        _forbid("Only the pharmacy owner or an admin can reset pharmacy data.")

    counts = await reset_pharmacy_data(db, ph_id)
    await log_activity(
        db,
        medical_store_id=ph_id,
        actor=user,
        action="PHARMACY_DATA_RESET",
        entity_type="medical_store",
        entity_id=ph_id,
        summary=f"Reset all data for pharmacy {ph_id}",
        meta=counts,
    )
    await db.commit()

    return success_response(
        ResetDataResponse(pharmacy_id=ph_id, **counts), "Pharmacy data reset"
    )
