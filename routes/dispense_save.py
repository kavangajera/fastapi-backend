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

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, File, Form, UploadFile
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import Feature
from middlewares.auth import auth_incoming_req
from models import Dispense, DrugReport, Medicine
from schemas.response_schema import Response_Schema, success_response
from schemas.save_dispense import DispenseSaveRequest, DispenseSaveResponse, DispensePatchRequest, DispensePatchLineInput
from schemas.save_invoice import InventoryUpdate
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.activity_service import build_search_blob, log_activity
from services.feature_gate import ensure_feature, within_limit
from services.inventory_service import reverse_dispense_quantities, subtract_dispense_quantities, reverse_single_dispense_qty
from services.pharmacy_authz import ensure_pharmacy_access
from services.record_id_service import stamp_on_create
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


def _filter_report_for_patch(report_data: dict, existing_rx_nos: set[str]) -> dict:
    """
    Filters the extracted document JSON to keep ONLY the dispenses whose
    rx_no is in `existing_rx_nos`. Drops any medicines that become empty.
    """
    import copy
    filtered = copy.deepcopy(report_data)
    medicines = filtered.get("medicines", [])
    
    kept_medicines = []
    for med in medicines:
        dispenses = med.get("dispenses", [])
        kept_dispenses = [
            d for d in dispenses
            if d.get("rx_no") in existing_rx_nos
        ]
        if kept_dispenses:
            med["dispenses"] = kept_dispenses
            kept_medicines.append(med)
            
    filtered["medicines"] = kept_medicines
    return filtered


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
    sub = await ensure_feature(db, body.medical_store_id, Feature.TOP_QUANTITY_DRUG_REPORT)

    # ── Plan quota gate: drugs reconciled per report ────────────────
    # DISABLED AT LAUNCH: no drug-count limit for any plan for now. The 250 cap
    # still lives in Plan.limits (Basic/Advanced) but is NOT enforced yet.
    # To re-enable, uncomment the block below (and keep `within_limit` imported).
    # n_drugs = len(body.medicines)
    # if not within_limit(sub, "drug_reconciliation_limit", n_drugs):
    #     cap = (sub.plan.limits or {}).get("drug_reconciliation_limit")
    #     raise HTTPException(
    #         status_code=status.HTTP_402_PAYMENT_REQUIRED,
    #         detail={
    #             "status_code": 402,
    #             "message": (
    #                 f"Your plan allows up to {cap} drugs reconciled per report; "
    #                 f"this report has {n_drugs}. Upgrade to Ultimate for unlimited."
    #             ),
    #             "data": None,
    #         },
    #     )

    # ── Validation gate (micro-gated by the store's plan) ───────────
    report_data = body.model_dump(mode="json")
    granted = set(sub.plan.features or []) if sub.plan is not None else None
    tier1 = validate_tier1(report_data, granted=granted)
    validation = await validate_tier2(db, report_data, tier1_report=tier1, granted=granted)

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

    # ── Duplicate rx_no detection ───────────────────────────────────
    incoming_rx_nos = [
        d.rx_no
        for med in body.medicines
        for d in med.dispenses
        if d.rx_no
    ]
    if incoming_rx_nos:
        existing = await db.execute(
            select(Dispense.rx_no).where(
                Dispense.medical_store_id == body.medical_store_id,
                Dispense.rx_no.in_(incoming_rx_nos),
                Dispense.IsDeleted == False,
            )
        )
        dupes = [row[0] for row in existing.all()]
        if dupes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "status_code": 409,
                    "message": (
                        f"Duplicate document: {len(dupes)} rx_no(s) already exist "
                        f"for this pharmacy. Duplicate rx_no: {dupes}"
                    ),
                    "data": {"duplicate_rx_nos": dupes},
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
        force_saved=forced,
        error_count=validation.summary.errors if forced else 0,
        validation_errors=(
            [a.model_dump(mode="json") for a in validation.alerts if a.severity == "ERROR"]
            if forced
            else None
        ),
    )
    await stamp_on_create(db, db_report, body.device_id)
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
        await stamp_on_create(db, db_med, body.device_id)
        db.add(db_med)
        await db.flush()

        for disp_in in med_in.dispenses:
            db_disp = _build_dispense(disp_in.model_dump(), db_med.id, body.medical_store_id)
            await stamp_on_create(db, db_disp, body.device_id)
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


@router.put(
    "/dispenses/{report_id}",
    response_model=Response_Schema,
    status_code=status.HTTP_200_OK,
    summary="Update a dispense report, fully replacing its medicines and dispenses",
)
async def update_dispense_report(
    report_id: int,
    body: DispenseSaveRequest,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, body.medical_store_id)
    sub = await ensure_feature(db, body.medical_store_id, Feature.TOP_QUANTITY_DRUG_REPORT)

    # ── Verify existing report ──────────────────────────────────────
    report_res = await db.execute(
        select(DrugReport).where(
            DrugReport.id == report_id,
            DrugReport.medical_store_id == body.medical_store_id
        )
    )
    existing_report = report_res.scalar_one_or_none()
    if not existing_report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispense report not found"
        )

    # ── Plan quota gate: drugs reconciled per report ────────────────
    n_drugs = len(body.medicines)
    if not within_limit(sub, "drug_reconciliation_limit", n_drugs):
        cap = (sub.plan.limits or {}).get("drug_reconciliation_limit")
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "status_code": 402,
                "message": (
                    f"Your plan allows up to {cap} drugs reconciled per report; "
                    f"this report has {n_drugs}. Upgrade to Ultimate for unlimited."
                ),
                "data": None,
            },
        )

    # ── Validation gate ─────────────────────────────────────────────
    report_data = body.model_dump(mode="json")
    granted = set(sub.plan.features or []) if sub.plan is not None else None
    tier1 = validate_tier1(report_data, granted=granted)
    validation = await validate_tier2(db, report_data, tier1_report=tier1, granted=granted)

    if validation.summary.blocking and not body.force_save:
        logger.info(
            "Dispense update blocked: ms_id={p} errors={e} warnings={w}",
            p=body.medical_store_id,
            e=validation.summary.errors,
            w=validation.summary.warnings,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "status_code": 422,
                "message": (
                    f"Dispense update blocked by {validation.summary.errors} validation "
                    "error(s). Fix the listed issues and resubmit, or set "
                    "`force_save: true` to persist anyway."
                ),
                "data": validation.model_dump(mode="json"),
            },
        )

    forced = validation.summary.blocking and body.force_save
    errors_by_med = _alerts_by_medicine(validation) if forced else {}

    # ── Persist (Full Replace) ──────────────────────────────────────
    try:
        # 1. Reverse old inventory quantities
        await reverse_dispense_quantities(
            db,
            medical_store_id=body.medical_store_id,
            drug_report_id=report_id,
        )
        
        # 2. Delete old medicines (which cascades to dispenses)
        await db.execute(
            Medicine.__table__.delete().where(Medicine.report_id == report_id)
        )
        await db.flush()

        # 3. Update report metadata
        existing_report.document_id = body.document_id
        existing_report.report_date = body.pharmacy.report_date
        existing_report.report_from_date = body.pharmacy.report_from_date
        existing_report.report_to_date = body.pharmacy.report_to_date
        existing_report.grand_total_rx_count = _to_int(body.grand_total.total_rx_count)
        existing_report.grand_total_price = _to_decimal(body.grand_total.total_price)
        existing_report.grand_total_cost = _to_decimal(body.grand_total.total_cost)
        existing_report.force_saved = forced
        existing_report.error_count = validation.summary.errors if forced else 0
        existing_report.validation_errors = (
            [a.model_dump(mode="json") for a in validation.alerts if a.severity == "ERROR"]
            if forced
            else None
        )

        # 4. Insert new medicines and dispenses
        total_dispenses = 0
        medicines_with_errors = 0
        for idx, med_in in enumerate(body.medicines):
            totals = med_in.totals
            med_errors = errors_by_med.get(idx)
            if med_errors:
                medicines_with_errors += 1
            db_med = Medicine(
                report_id=existing_report.id,
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
            await stamp_on_create(db, db_med, body.device_id)
            db.add(db_med)
            await db.flush()

            for disp_in in med_in.dispenses:
                db_disp = _build_dispense(disp_in.model_dump(), db_med.id, body.medical_store_id)
                await stamp_on_create(db, db_disp, body.device_id)
                db.add(db_disp)
                total_dispenses += 1

        await db.flush()

        # 5. Apply new inventory quantities
        inventory_updates_raw = await subtract_dispense_quantities(
            db,
            medical_store_id=body.medical_store_id,
            drug_report_id=existing_report.id,
        )

        await log_activity(
            db,
            medical_store_id=body.medical_store_id,
            actor=user,
            action="DISPENSE_REPORT_UPDATED",
            entity_type="drug_report",
            entity_id=existing_report.id,
            summary=(
                f"Updated dispense report "
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
        logger.exception("Failed to update dispense report: {err}", err=exc)
        raise

    logger.info(
        "Dispense report updated: report_id={r} ms_id={ph} meds={m} disp={d} warnings={w} info={i}",
        r=existing_report.id,
        ph=body.medical_store_id,
        m=len(body.medicines),
        d=total_dispenses,
        w=validation.summary.warnings,
        i=validation.summary.info,
    )

    return success_response(
        DispenseSaveResponse(
            report_id=existing_report.id,
            medical_store_id=body.medical_store_id,
            medicines_saved=len(body.medicines),
            dispenses_saved=total_dispenses,
            force_saved=forced,
            medicines_with_errors=medicines_with_errors,
            inventory_updates=[InventoryUpdate(**u) for u in inventory_updates_raw],
            validation=validation,
        ),
        "Dispense report updated successfully",
        status_code=200,
    )


@router.patch(
    "/dispenses",
    response_model=Response_Schema,
    status_code=status.HTTP_200_OK,
    summary="Partially update dispenses by rx_no using full JSON with validation",
    description=(
        "Accepts a full DispenseSaveRequest JSON. Filters for existing rx_nos, "
        "runs Tier 1 and Tier 2 validation on that subset, and patches the "
        "existing dispenses. Respects force_save just like POST /dispenses."
    ),
)
async def patch_dispenses(
    body: DispenseSaveRequest,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, body.medical_store_id)
    sub = await ensure_feature(db, body.medical_store_id, Feature.TOP_QUANTITY_DRUG_REPORT)

    # 1. Collect all rx_no from the incoming request
    incoming_rx_nos = [
        d.rx_no
        for med in body.medicines
        for d in med.dispenses
        if d.rx_no
    ]
    if not incoming_rx_nos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No rx_no values found in the provided document."
        )

    # 2. Find which ones actually exist in the DB for this pharmacy
    rows = await db.execute(
        select(Dispense).where(
            Dispense.medical_store_id == body.medical_store_id,
            Dispense.rx_no.in_(incoming_rx_nos),
            Dispense.IsDeleted == False,
        )
    )
    existing_map: dict[str, Dispense] = {}
    for disp in rows.scalars().all():
        existing_map[disp.rx_no] = disp

    if not existing_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="None of the rx_no values in the document exist in the database for this pharmacy."
        )

    # 3. Filter the report data so validation ONLY runs on matched rx_nos
    report_data_dump = body.model_dump(mode="json")
    filtered_report_data = _filter_report_for_patch(report_data_dump, set(existing_map.keys()))

    # 4. Run Tier 1 and Tier 2 validation on the filtered subset
    granted = set(sub.plan.features or []) if sub.plan is not None else None
    tier1 = validate_tier1(filtered_report_data, granted=granted)
    validation = await validate_tier2(db, filtered_report_data, tier1_report=tier1, granted=granted)

    if validation.summary.blocking and not body.force_save:
        logger.info(
            "Dispense JSON patch blocked: ms_id={p} errors={e} warnings={w}",
            p=body.medical_store_id,
            e=validation.summary.errors,
            w=validation.summary.warnings,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "status_code": 422,
                "message": (
                    f"JSON patch blocked by {validation.summary.errors} validation "
                    "error(s). Fix the listed issues and resubmit, or set "
                    "`force_save: true` to persist anyway."
                ),
                "data": validation.model_dump(mode="json"),
            },
        )

    forced = validation.summary.blocking and body.force_save

    # 5. Patch the matched dispenses
    medicine_ids = {d.medicine_id for d in existing_map.values()}
    med_rows = await db.execute(select(Medicine).where(Medicine.id.in_(medicine_ids)))
    medicine_map: dict[int, Medicine] = {m.id: m for m in med_rows.scalars().all()}

    inventory_updates = []
    patched_count = 0
    medicines_with_errors = 0
    errors_by_med = _alerts_by_medicine(validation) if forced else {}

    try:
        filtered_body = DispenseSaveRequest.model_validate(filtered_report_data)
        
        for idx, med_in in enumerate(filtered_body.medicines):
            med_errors = errors_by_med.get(idx)
            if med_errors:
                medicines_with_errors += 1
                
            for disp_in in med_in.dispenses:
                db_disp = existing_map[disp_in.rx_no]
                parent_med = medicine_map[db_disp.medicine_id]

                # Reverse old inventory
                if db_disp.qty_disp is not None:
                    rev = await reverse_single_dispense_qty(
                        db,
                        medical_store_id=body.medical_store_id,
                        ndc=parent_med.ndc,
                        qty_disp=db_disp.qty_disp,
                        direction=1,
                    )
                    if rev:
                        inventory_updates.append(rev)

                # Apply new fields
                patch_data = disp_in.model_dump(exclude_unset=True, exclude={"rx_no"})
                for field, value in patch_data.items():
                    if value is not None:
                        if field in ("qty_disp", "qty_ord", "price", "ins_paid"):
                            setattr(db_disp, field, _to_decimal(value))
                        elif field == "days_supply":
                            setattr(db_disp, field, _to_int(value))
                        else:
                            setattr(db_disp, field, value)

                # Subtract new inventory
                if db_disp.qty_disp is not None:
                    sub_inv = await reverse_single_dispense_qty(
                        db,
                        medical_store_id=body.medical_store_id,
                        ndc=parent_med.ndc,
                        qty_disp=db_disp.qty_disp,
                        direction=-1,
                    )
                    if sub_inv:
                        inventory_updates.append(sub_inv)

                patched_count += 1

        # Recalculate parent Medicine totals
        for med_id in medicine_ids:
            med = medicine_map[med_id]
            disp_rows = await db.execute(
                select(Dispense).where(
                    Dispense.medicine_id == med_id,
                    Dispense.IsDeleted == False,
                )
            )
            dispenses = list(disp_rows.scalars().all())
            med.total_rx_count = len(dispenses)
            med.total_price = sum((d.price or Decimal("0")) for d in dispenses) or None
            med.total_ins_paid = sum((d.ins_paid or Decimal("0")) for d in dispenses) or None

        # Recalculate DrugReport grand totals
        report_ids = {med.report_id for med in medicine_map.values()}
        for report_id in report_ids:
            report_res = await db.execute(select(DrugReport).where(DrugReport.id == report_id))
            report = report_res.scalar_one()
            med_res = await db.execute(select(Medicine).where(Medicine.report_id == report_id))
            meds = list(med_res.scalars().all())
            report.grand_total_rx_count = sum(m.total_rx_count or 0 for m in meds) or None
            report.grand_total_price = sum(m.total_price or Decimal("0") for m in meds) or None

        await log_activity(
            db,
            medical_store_id=body.medical_store_id,
            actor=user,
            action="DISPENSE_PATCHED",
            entity_type="dispense",
            entity_id=None,
            summary=f"Patched {patched_count} dispense(s) via JSON validation",
            search_blob=build_search_blob(*(d.rx_no for d in body.medicines for d in d.dispenses if d.rx_no)),
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Failed to patch dispenses: {err}", err=exc)
        raise

    logger.info(
        "Dispenses patched: ms_id={ph} count={n}",
        ph=body.medical_store_id,
        n=patched_count,
    )

    return success_response(
        DispenseSaveResponse(
            report_id=list(report_ids)[0] if report_ids else 0, # Return arbitrary report_id since patch crosses reports
            medical_store_id=body.medical_store_id,
            medicines_saved=len(filtered_body.medicines),
            dispenses_saved=patched_count,
            force_saved=forced,
            medicines_with_errors=medicines_with_errors,
            inventory_updates=[InventoryUpdate(**u) for u in inventory_updates],
            validation=validation,
        ),
        "Dispenses patched successfully",
        status_code=200,
    )


@router.patch(
    "/dispenses/document",
    response_model=Response_Schema,
    status_code=status.HTTP_200_OK,
    summary="Extract JSON for a dispense patch from document and run Tier-1 (No DB write)",
)
async def patch_dispenses_from_document(
    medical_store_id: int = Form(..., description="Medical store the doc belongs to"),
    file: UploadFile = File(..., description="The corrected dispense document (PDF/Excel)"),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, medical_store_id)
    sub = await ensure_feature(db, medical_store_id, Feature.TOP_QUANTITY_DRUG_REPORT)

    import asyncio
    from services.document_extractor import extract_report_from_file
    from fastapi import UploadFile

    file_bytes = await file.read()
    filename = file.filename or "unknown"
    
    # 1. Extract JSON from the file synchronously
    report_data = await asyncio.to_thread(extract_report_from_file, file_bytes, filename)
    report_data["medical_store_id"] = medical_store_id
    
    # Validate against our schema to ensure structural correctness (Pydantic will coerce numbers now)
    body = DispenseSaveRequest(**report_data)

    # 2. Collect all rx_no from the incoming document
    incoming_rx_nos = [
        d.rx_no
        for med in body.medicines
        for d in med.dispenses
        if d.rx_no
    ]
    if not incoming_rx_nos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No rx_no values found in the provided document."
        )

    # 3. Find which ones actually exist in the DB for this pharmacy
    rows = await db.execute(
        select(Dispense).where(
            Dispense.medical_store_id == medical_store_id,
            Dispense.rx_no.in_(incoming_rx_nos),
            Dispense.IsDeleted == False,
        )
    )
    existing_map: dict[str, Dispense] = {}
    for disp in rows.scalars().all():
        existing_map[disp.rx_no] = disp

    if not existing_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="None of the rx_no values in the document exist in the database for this pharmacy."
        )

    # 4. Filter the report data so validation ONLY runs on matched rx_nos
    report_data_dump = body.model_dump(mode="json")
    filtered_report_data = _filter_report_for_patch(report_data_dump, set(existing_map.keys()))

    # 5. Run Tier 1 validation only (matching POST /documents/process worker logic)
    granted = set(sub.plan.features or []) if sub.plan is not None else None
    tier1 = validate_tier1(filtered_report_data, granted=granted)
    
    filtered_report_data["validation"] = tier1.model_dump(mode="json")

    return success_response(
        filtered_report_data,
        "Document extracted and Tier-1 validation complete. Submit to PATCH /dispenses to save.",
        status_code=200,
    )
