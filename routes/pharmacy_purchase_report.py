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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import UserRole
from middlewares.auth import auth_incoming_req
from models import DrugReport, Medicine
from models.pharmacy import Pharmacy
from schemas.pharmacy_purchase_report import (
    DrugReportListItem,
    DrugReportResponse,
    MedicineResponse,
)
from schemas.system_internal_user_schema import System_Internal_User_Schema
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
    response_model=list[DrugReportListItem],
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
        stmt = stmt.where(DrugReport.medical_store_id.in_(ph_ids))
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ── GET /reports/{report_id} ──────────────────────────────────────────────────


@router.get(
    "/{report_id:int}",
    response_model=DrugReportResponse,
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
    return report


# ── GET /reports/{report_id}/medicines/{ndc} ──────────────────────────────────


@router.get(
    "/{report_id:int}/medicines/{ndc}",
    response_model=MedicineResponse,
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

    result = await db.execute(
        select(Medicine).where(Medicine.report_id == report_id, Medicine.ndc == ndc)
    )
    med = result.scalar_one_or_none()
    if not med:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Medicine with NDC {ndc} not found in report {report_id}.",
        )
    return med


# ── DELETE /reports/{report_id} ───────────────────────────────────────────────


@router.delete(
    "/{report_id:int}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a report and all its associated data",
)
async def delete_report(
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
    report.IsDeleted = True
    await db.commit()
