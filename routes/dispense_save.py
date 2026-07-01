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
from schemas.audit_input import apply_record_identifier_on_create
from schemas.response_schema import Response_Schema, success_response
from schemas.save_dispense import DispenseSaveRequest, DispenseSaveResponse
from schemas.save_invoice import InventoryUpdate
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.activity_service import build_search_blob, log_activity
from services.inventory_service import subtract_dispense_quantities
from services.pharmacy_authz import ensure_pharmacy_access
from services.report_service import _build_dispense, _to_decimal, _to_int
from services.validation import validate_tier1, validate_tier2

router = APIRouter(tags=["Dispense Reports"])


def _alerts_by_medicine(validation) -> dict[int, list[dict]]:
    """Group ERROR-severity alerts by their `medicine_index`."""
    grouped: dict[int, list[dict]] = {}
    for alert in validation.alerts:
        if alert.severity != "ERROR" or alert.medicine_index is None:
            continue
        grouped.setdefault(alert.medicine_index, []).append(alert.model_dump(mode="json"))
    return grouped


@router.post(
    "/dispenses",
    response_model=Response_Schema,
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

    # Block only when there are errors AND the owner has not opted to force-save.
    if validation.summary.blocking and not body.force_save:
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
                    "error(s). Fix the listed issues and resubmit, or set "
                    "`force_save: true` to persist anyway."
                ),
                "data": validation.model_dump(mode="json"),
            },
        )

    forced = validation.summary.blocking and body.force_save
    errors_by_med = _alerts_by_medicine(validation) if forced else {}

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
        force_saved=forced,
        error_count=validation.summary.errors if forced else 0,
        validation_errors=(
            [a.model_dump(mode="json") for a in validation.alerts if a.severity == "ERROR"]
            if forced
            else None
        ),
    )
    apply_record_identifier_on_create(db_report, body)
    db.add(db_report)
    await db.flush()

    total_dispenses = 0
    medicines_with_errors = 0
    for idx, med_in in enumerate(body.medicines):
        totals = med_in.totals
        med_errors = errors_by_med.get(idx)
        if med_errors:
            medicines_with_errors += 1
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
            has_errors=bool(med_errors),
            validation_errors=med_errors,
        )
        apply_record_identifier_on_create(db_med, med_in)
        db.add(db_med)
        await db.flush()

        for disp_in in med_in.dispenses:
            db_disp = _build_dispense(disp_in.model_dump(), db_med.id)
            apply_record_identifier_on_create(db_disp, disp_in)
            db.add(db_disp)
            total_dispenses += 1

    await db.flush()

    try:
        inventory_updates_raw = await subtract_dispense_quantities(
            db,
            medical_store_id=body.medical_store_id,
            drug_report_id=db_report.id,
        )
        await log_activity(
            db,
            medical_store_id=body.medical_store_id,
            actor=user,
            action="DISPENSE_FORCE_SAVED" if forced else "DISPENSE_SAVED",
            entity_type="drug_report",
            entity_id=db_report.id,
            summary=(
                f"{'Force-saved' if forced else 'Saved'} dispense report "
                f"({len(body.medicines)} medicines, {total_dispenses} dispenses)"
                + (f" with {validation.summary.errors} error(s)" if forced else "")
            ),
            search_blob=build_search_blob(
                *(m.drug_name for m in body.medicines),
                *(m.ndc for m in body.medicines),
            ),
            error_count=validation.summary.errors if forced else 0,
            meta={
                "medicines": len(body.medicines),
                "dispenses": total_dispenses,
                "medicines_with_errors": medicines_with_errors,
                "rx_count": _to_int(body.grand_total.total_rx_count),
                "total_price": body.grand_total.total_price,
                "report_from_date": body.pharmacy.report_from_date,
                "report_to_date": body.pharmacy.report_to_date,
                "warnings": validation.summary.warnings,
            },
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

    return success_response(
        DispenseSaveResponse(
            report_id=db_report.id,
            medical_store_id=body.medical_store_id,
            medicines_saved=len(body.medicines),
            dispenses_saved=total_dispenses,
            force_saved=forced,
            medicines_with_errors=medicines_with_errors,
            inventory_updates=[InventoryUpdate(**u) for u in inventory_updates_raw],
            validation=validation,
        ),
        "Dispense report saved successfully",
        status_code=201,
    )
