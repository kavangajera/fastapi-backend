"""
routes/dispense_validate.py
───────────────────────────
`POST /dispenses/validate` — run Tier-1 + Tier-2 validation on a dispense
JSON without persisting anything. Used by the UI for live alert feedback
after each form edit (and during dev / Swagger testing).

Body is the same `DispenseSaveRequest` used by `POST /dispenses`, so the
UI never needs to reshape data between validate and save.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from middlewares.auth import auth_incoming_req
from schemas.save_dispense import DispenseSaveRequest
from schemas.system_internal_user_schema import System_Internal_User_Schema
from schemas.validation import ValidationReport
from services.pharmacy_authz import ensure_pharmacy_access
from services.validation import validate_tier1, validate_tier2

router = APIRouter(tags=["Dispense Reports"])


@router.post(
    "/dispenses/validate",
    response_model=ValidationReport,
    summary="Validate a dispense JSON (Tier-1 + FDA Tier-2). No DB write.",
    description=(
        "Runs the full validation engine and returns the alert report. Use "
        "this from the UI after every form edit to surface fixes the user "
        "needs to make before `POST /dispenses` will accept the body. "
        "First call for a given NDC hits FDA (~1–2 s/NDC); subsequent calls "
        "are served from `medicine_ndc_cache`."
    ),
)
async def validate_dispense(
    body: DispenseSaveRequest,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
) -> ValidationReport:
    await ensure_pharmacy_access(db, user, body.medical_store_id)
    report_data = body.model_dump(mode="json")
    tier1 = validate_tier1(report_data)
    return await validate_tier2(db, report_data, tier1_report=tier1)
