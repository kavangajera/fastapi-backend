"""
routes/pharmacy_purchase_report.py
──────────────────────────────────
Read-only async endpoints for dispense reports. Persistence happens via
`POST /dispenses` — see `routes/dispense_save.py`.

Endpoints
─────────
GET  /reports/                            List reports (pharmacy-scoped for non-admins)
GET  /reports/{report_id}                 Full report with medicines + dispenses
GET  /reports/{report_id}/medicines/{ndc} One medicine
DELETE /reports/{report_id}               Delete a report
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import Feature, ProcessType, UserRole
from middlewares.auth import auth_incoming_req
from models import Dispense, DrugReport, Medicine
from models.pharmacy import Pharmacy
from schemas.pending_document import PendingDocumentItem
from schemas.pharmacy_purchase_report import (
    DrugReportListItemWrapped,
    DrugReportResponse,
    MedicineResponse,
)
from schemas.response_schema import Response_Schema, success_response
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.feature_gate import ensure_feature, entitled_store_ids
from services.inventory_service import reverse_dispense_quantities
from services.pending_documents import document_pending_state, fetch_pending_documents
from services.pharmacy_authz import ensure_pharmacy_access

router = APIRouter(prefix="/reports", tags=["Drug Dispensed Reports"])


async def _accessible_medical_store_ids(
    db: AsyncSession, user: System_Internal_User_Schema
) -> list[int] | None:
    if user.role == UserRole.ADMIN:
        return None
    if user.role == UserRole.PHARMACY_OWNER:
        result = await db.execute(
            select(Pharmacy.medical_store_id).where(Pharmacy.user_id == user.user_id)
        )
        return [row[0] for row in result.all()]
    return [user.medical_store_id] if user.medical_store_id else []


# ── GET /reports/ ─────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=Response_Schema,
    summary="List dispense reports (pharmacy-scoped for non-admin)",
)
async def list_reports(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    stmt = select(DrugReport).order_by(DrugReport.id.desc()).offset(skip).limit(limit)
    ph_ids = await _accessible_medical_store_ids(db, user)
    if ph_ids is not None:
        # Only show reports for stores entitled to dispensary intelligence.
        ph_ids = await entitled_store_ids(db, ph_ids, Feature.TOP_QUANTITY_DRUG_REPORT)
        stmt = stmt.where(DrugReport.medical_store_id.in_(ph_ids))
    result = await db.execute(stmt)
    reports = [DrugReportListItemWrapped.model_validate(r) for r in result.scalars().all()]

    pending_items: list[PendingDocumentItem] = []
    if skip == 0 and ph_ids is not None:
        pending_docs = await fetch_pending_documents(
            db,
            process_type=ProcessType.DISPENSE.value,
            medical_store_ids=ph_ids,
            saved_model=DrugReport,
        )
        pending_items = [
            PendingDocumentItem(
                doc_key=d.doc_key,
                state=document_pending_state(d.status),
                original_filename=d.original_filename,
                error_message=d.error_message,
                created_at=d.created_at,
                updated_at=d.updated_at,
            )
            for d in pending_docs
        ]

    return success_response([*pending_items, *reports], "Reports retrieved successfully")


# ── GET /reports/{report_id} ──────────────────────────────────────────────────


@router.get(
    "/{report_id:int}",
    response_model=Response_Schema,
    summary="Get a full dispense report",
)
async def get_report(
    report_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    result = await db.execute(select(DrugReport).where(DrugReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report {report_id} not found.",
        )
    await ensure_pharmacy_access(db, user, report.medical_store_id)
    await ensure_feature(db, report.medical_store_id, Feature.TOP_QUANTITY_DRUG_REPORT)
    return success_response(
        DrugReportResponse.model_validate(report), "Report retrieved successfully"
    )


# ── GET /reports/{report_id}/medicines/{ndc} ──────────────────────────────────


@router.get(
    "/{report_id:int}/medicines/{ndc}",
    response_model=Response_Schema,
    summary="Get a specific medicine (by NDC) within a report",
)
async def get_medicine_by_ndc(
    report_id: int,
    ndc: str,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    report_lookup = await db.execute(
        select(DrugReport.medical_store_id).where(DrugReport.id == report_id)
    )
    report_ph = report_lookup.scalar_one_or_none()
    if report_ph is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report {report_id} not found.",
        )
    await ensure_pharmacy_access(db, user, report_ph)
    await ensure_feature(db, report_ph, Feature.TOP_QUANTITY_DRUG_REPORT)

    result = await db.execute(
        select(Medicine).where(Medicine.report_id == report_id, Medicine.ndc == ndc)
    )
    med = result.scalar_one_or_none()
    if not med:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Medicine with NDC {ndc} not found in report {report_id}.",
        )
    return success_response(
        MedicineResponse.model_validate(med), "Medicine retrieved successfully"
    )


# ── DELETE /reports/{report_id} ───────────────────────────────────────────────


@router.delete(
    "/{report_id:int}",
    response_model=Response_Schema,
    summary="Delete a report and all its associated data",
)
async def delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    # Locked for the duration of the transaction. Without it two concurrent
    # deletes of the same report both read it as live and both run the
    # inventory reversal, silently adding the dispensed quantities back twice.
    result = await db.execute(
        select(DrugReport).where(DrugReport.id == report_id).with_for_update()
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report {report_id} not found.",
        )
    await ensure_pharmacy_access(db, user, report.medical_store_id)
    await ensure_feature(db, report.medical_store_id, Feature.TOP_QUANTITY_DRUG_REPORT)

    # Saving this report drew its quantities OUT of inventory
    # (services/inventory_service.subtract_dispense_quantities). Deleting it
    # has to put them back, or the shelf count keeps shrinking every time a
    # mis-uploaded report is removed. Runs BEFORE the rows are flagged: the
    # reversal reads medicines/dispenses through the ORM, which filters
    # soft-deleted rows out automatically.
    inventory_updates = await reverse_dispense_quantities(
        db, medical_store_id=report.medical_store_id, drug_report_id=report_id
    )

    # Soft-delete the children too. The ORM cascade is delete-orphan (a hard
    # delete), which this path deliberately doesn't use — but leaving the rows
    # live would keep them visible to everything that queries dispenses
    # directly. It also matters for re-upload: `uq_dispenses_store_rx_no_active`
    # is keyed on a generated column that goes NULL once a row is deleted, so
    # flagging these rows is what actually frees their rx_nos for the corrected
    # document (see alembic c2d3e4f5a6b7).
    med_rows = (
        await db.execute(select(Medicine).where(Medicine.report_id == report_id))
    ).scalars().all()
    dispenses_removed = 0
    for med in med_rows:
        disp_rows = (
            await db.execute(select(Dispense).where(Dispense.medicine_id == med.id))
        ).scalars().all()
        for disp in disp_rows:
            disp.IsDeleted = True
            dispenses_removed += 1
        med.IsDeleted = True

    report.IsDeleted = True
    await db.commit()

    logger.info(
        "Report deleted: report_id={r} ms_id={ph} medicines={m} dispenses={d} inventory_touched={i}",
        r=report_id,
        ph=report.medical_store_id,
        m=len(med_rows),
        d=dispenses_removed,
        i=len(inventory_updates),
    )
    return success_response(
        {
            "report_id": report_id,
            "medicines_removed": len(med_rows),
            "dispenses_removed": dispenses_removed,
            "inventory_updates": inventory_updates,
        },
        "Report deleted and inventory restored",
    )
