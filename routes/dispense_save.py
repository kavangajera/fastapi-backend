"""
routes/dispense_save.py
───────────────────────
`POST /dispenses` — persist a (possibly user-edited) dispense report
JSON and apply −qty per medicine to `medicine_inventory`.

Validation gate:
    1. Run Tier-1 + Tier-2 against the submitted body.
    2. If `summary.blocking` (any ERROR severity) → 422 with the full
       ValidationReport in `detail`. No DB write.
    3. Otherwise persist DrugReport + Medicine + Dispense, update
       inventory, and return DispenseSaveResponse with the validation
       report attached so the UI can still surface warnings/info.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from middlewares.auth import auth_incoming_req
from models import Dispense, DrugReport, Medicine
from schemas.save_dispense import DispenseSaveRequest, DispenseSaveResponse
from schemas.save_invoice import InventoryUpdate
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.inventory_service import subtract_dispense_quantities
from services.pharmacy_authz import ensure_pharmacy_access
from services.report_service import _build_dispense, _to_decimal, _to_int
from services.validation import validate_tier1, validate_tier2

router = APIRouter(tags=["Dispense Reports"])


@router.post(
    "/dispenses",
    response_model=DispenseSaveResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Validate, persist a dispense report JSON, and update inventory (-qty)",
    description=(
        "Runs the full validation engine (Tier 1 + FDA Tier 2) against the body. "
        "If any ERROR-severity alert is present, returns 422 with the alert list "
        "in `detail` and writes nothing. Otherwise creates one `DrugReport` + N "
        "`Medicine` + M `Dispense` rows, subtracts dispensed qty from "
        "`medicine_inventory`, and returns the persisted ids plus the (non-blocking) "
        "validation report."
    ),
)
async def save_dispense_report(
    body: DispenseSaveRequest,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, body.medical_store_id)

    # ── Validation gate ─────────────────────────────────────────────
    report_data = body.model_dump(mode="json")
    tier1 = validate_tier1(report_data)
    validation = await validate_tier2(db, report_data, tier1_report=tier1)
    if validation.summary.blocking:
        logger.info(
            "Dispense save blocked: ms_id={p} errors={e} warnings={w}",
            p=body.medical_store_id,
            e=validation.summary.errors,
            w=validation.summary.warnings,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "status_code": 422,
                "message": (
                    f"Dispense save blocked by {validation.summary.errors} validation "
                    "error(s). Fix the listed issues and resubmit."
                ),
                "data": validation.model_dump(mode="json"),
            },
        )

    # ── Persist ─────────────────────────────────────────────────────
    db_report = DrugReport(
        medical_store_id=body.medical_store_id,
        document_id=body.document_id,
        report_date=body.pharmacy.report_date,
        report_from_date=body.pharmacy.report_from_date,
        report_to_date=body.pharmacy.report_to_date,
        grand_total_rx_count=_to_int(body.grand_total.total_rx_count),
        grand_total_price=_to_decimal(body.grand_total.total_price),
        grand_total_cost=_to_decimal(body.grand_total.total_cost),
    )
    db.add(db_report)
    await db.flush()

    total_dispenses = 0
    for med_in in body.medicines:
        totals = med_in.totals
        db_med = Medicine(
            report_id=db_report.id,
            drug_name=med_in.drug_name,
            ndc=med_in.ndc,
            inventory_bucket=med_in.inventory_bucket,
            lot_no_exp_date=med_in.lot_no_exp_date,
            total_packs=_to_decimal(totals.packs) if totals else None,
            total_rx_count=_to_int(totals.total_rx_count) if totals else None,
            total_ins_paid=_to_decimal(totals.total_ins_paid) if totals else None,
            total_price=_to_decimal(totals.total_price) if totals else None,
            total_cost=_to_decimal(totals.total_cost) if totals else None,
        )
        db.add(db_med)
        await db.flush()

        for disp_in in med_in.dispenses:
            db.add(_build_dispense(disp_in.model_dump(), db_med.id))
            total_dispenses += 1

    await db.flush()

    try:
        inventory_updates_raw = await subtract_dispense_quantities(
            db,
            medical_store_id=body.medical_store_id,
            drug_report_id=db_report.id,
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Failed to save dispense report: {err}", err=exc)
        raise

    assert Dispense is not None  # keep import for ORM registration

    logger.info(
        "Dispense report saved: report_id={r} ms_id={ph} meds={m} disp={d} warnings={w} info={i}",
        r=db_report.id,
        ph=body.medical_store_id,
        m=len(body.medicines),
        d=total_dispenses,
        w=validation.summary.warnings,
        i=validation.summary.info,
    )

    return DispenseSaveResponse(
        report_id=db_report.id,
        medical_store_id=body.medical_store_id,
        medicines_saved=len(body.medicines),
        dispenses_saved=total_dispenses,
        inventory_updates=[InventoryUpdate(**u) for u in inventory_updates_raw],
        validation=validation,
    )
