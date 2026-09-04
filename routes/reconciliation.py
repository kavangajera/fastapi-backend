"""
routes/reconciliation.py
────────────────────────
`GET /pharmacy/{ph_id}/reconciliation/invoice-vs-billed`
Invoice-vs-billed inventory cross-reconciliation.

🔒 Ultimate-only (`invoice_billed_cross_reconciliation`). Compares, per NDC,
what the store purchased (invoices) against what it billed out (dispense
reports), flagging NDCs dispensed in greater quantity than ever invoiced.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import Feature
from middlewares.auth import auth_incoming_req
from schemas.reconciliation import ReconciliationResponse
from schemas.response_schema import Response_Schema, success_response
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.feature_gate import ensure_feature
from services.pharmacy_authz import ensure_pharmacy_access
from services.reconciliation_service import invoice_vs_billed

router = APIRouter(tags=["Reconciliation"])


@router.get(
    "/pharmacy/{ph_id}/reconciliation/invoice-vs-billed",
    response_model=Response_Schema,
    summary="Invoice-vs-billed cross-reconciliation (Ultimate)",
    description=(
        "Per NDC, compares purchased quantity (invoices) against billed-out "
        "quantity (dispense reports). `status` is OVER_BILLED (dispensed > "
        "invoiced), UNDER_DISPENSED (invoiced > dispensed), MATCHED, or "
        "NEVER_INVOICED (dispensed but no invoice line item exists for this "
        "NDC at all — `message` on that row reads 'No Invoice Record Found').\n\n"
        "🔒 **Requires the Ultimate plan** (`invoice_billed_cross_reconciliation`)."
    ),
)
async def invoice_vs_billed_reconciliation(
    ph_id: int = Path(..., description="medical_store_id"),
    only_mismatch: bool = Query(False, description="Only rows where dispensed ≠ invoiced"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, ph_id)
    await ensure_feature(db, ph_id, Feature.INVOICE_BILLED_CROSS_RECONCILIATION)

    rows, summary = await invoice_vs_billed(db, medical_store_id=ph_id, only_mismatch=only_mismatch)
    page = rows[skip : skip + limit]
    return success_response(
        ReconciliationResponse.model_validate(
            {
                "medical_store_id": ph_id,
                "summary": summary,
                "items": page,
                "total": len(rows),
                "skip": skip,
                "limit": limit,
            }
        ).model_dump(),
        "Reconciliation completed",
    )
