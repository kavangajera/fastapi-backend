"""
routes/refills.py
─────────────────
`GET    /pharmacy/{ph_id}/refills`                 — refill-due customer list
`DELETE /pharmacy/{ph_id}/refills/{patient_key}`   — stop tracking a customer

The list is derived (see `services/refill_service.py`) from the latest fill per
patient + drug. Dismissing a customer records a non-destructive opt-out in
`refill_dismissals` — the dispense history stays intact for audit / inventory.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from middlewares.auth import auth_incoming_req
from models import RefillDismissal
from schemas.refills import RefillDismissResponse, RefillListResponse, RefillRow
from schemas.response_schema import Response_Schema, success_response
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.activity_service import log_activity
from services.pharmacy_authz import ensure_pharmacy_access
from services.refill_service import build_refill_list

router = APIRouter(tags=["Refills"])


@router.get(
    "/pharmacy/{ph_id}/refills",
    response_model=Response_Schema,
    summary="Customers due for a refill (latest fill + days_supply)",
    description=(
        "Refill-due list derived from dispense history: one row per customer + "
        "medicine using their most recent fill. `next_due = last fill + "
        "days_supply`; `status` is OVERDUE / DUE_SOON / OK / UNKNOWN. Filter by "
        "status, medicine, customer, or a due-window in days."
    ),
)
async def list_refills(
    ph_id: int = Path(..., description="medical_store_id"),
    status: str | None = Query(None, description="OVERDUE | DUE_SOON | OK | UNKNOWN"),
    medicine: str | None = Query(None, description="Substring match on drug name or NDC"),
    customer: str | None = Query(None, description="Substring match on customer name"),
    due_within_days: int | None = Query(
        None, description="Only show fills due within N days (includes overdue)"
    ),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, ph_id)
    entries = await build_refill_list(db, medical_store_id=ph_id)

    if status:
        entries = [e for e in entries if e.status == status.upper()]
    if medicine:
        needle = medicine.lower()
        entries = [
            e for e in entries if needle in (e.drug_name or "").lower() or needle in e.ndc.lower()
        ]
    if customer:
        needle = customer.lower()
        entries = [e for e in entries if needle in (e.customer_name or "").lower()]
    if due_within_days is not None:
        entries = [
            e
            for e in entries
            if e.days_remaining is not None and e.days_remaining <= due_within_days
        ]

    items = [RefillRow(**vars(e)) for e in entries]
    return success_response(
        RefillListResponse(medical_store_id=ph_id, items=items, total=len(items)),
        "Refills retrieved successfully",
    )


@router.delete(
    "/pharmacy/{ph_id}/refills/{patient_key}",
    response_model=Response_Schema,
    summary="Stop tracking a customer (or one of their medicines) for refills",
    description=(
        "Records a refill dismissal so the customer drops off the list. Omit "
        "`drug_ndc` to dismiss the customer for every medicine; pass an NDC to "
        "dismiss just that one. Dispense history is preserved."
    ),
)
async def dismiss_refill(
    ph_id: int = Path(..., description="medical_store_id"),
    patient_key: str = Path(..., description="Hashed patient key from the refill list"),
    drug_ndc: str | None = Query(None, description="NDC to dismiss; omit for all drugs"),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, ph_id)

    ndc_value = drug_ndc or ""
    # Idempotent: ignore if the dismissal already exists.
    stmt = (
        mysql_insert(RefillDismissal)
        .values(
            medical_store_id=ph_id,
            patient_key=patient_key,
            drug_ndc=ndc_value,
            dismissed_by_user_id=user.user_id,
        )
        .prefix_with("IGNORE")
    )
    await db.execute(stmt)

    await log_activity(
        db,
        medical_store_id=ph_id,
        actor=user,
        action="REFILL_CUSTOMER_DISMISSED",
        entity_type="refill",
        summary=(
            f"Stopped refill tracking for patient {patient_key}"
            + (f" / NDC {drug_ndc}" if drug_ndc else " (all medicines)")
        ),
        meta={"patient_key": patient_key, "drug_ndc": drug_ndc},
    )
    await db.commit()

    return success_response(
        RefillDismissResponse(
            medical_store_id=ph_id,
            patient_key=patient_key,
            drug_ndc=drug_ndc,
            dismissed=True,
        ),
        "Refill customer dismissed successfully",
    )
