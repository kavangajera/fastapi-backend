"""
routes/audit_report.py
──────────────────────
`GET /pharmacy/{ph_id}/audit-report` — audit / compliance view.

Read-only aggregation over existing tables:
    - `documents`         → parsing / processing failures
    - `drug_reports` +
      `medicines`         → force-saved reports and their per-row validation errors
    - `activity_log`      → period counts for the summary

No new tables; complements the operational `/activity` feed with an
error-centric, audit-friendly shape.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import DocumentStatus
from middlewares.auth import auth_incoming_req
from models import ActivityLog, Document, DrugReport
from schemas.audit_report import (
    AuditReportResponse,
    AuditSummary,
    ParsingError,
    ValidationErrorRow,
)
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.pharmacy_authz import ensure_pharmacy_access

router = APIRouter(tags=["Audit Report"])

_FAILED_STATUSES = (DocumentStatus.FAILED.value, DocumentStatus.FAILED_PERMANENTLY.value)


@router.get(
    "/pharmacy/{ph_id}/audit-report",
    response_model=AuditReportResponse,
    summary="Audit-friendly report of parsing & validation errors over a period",
    description=(
        "Aggregates document processing failures and force-saved dispense reports "
        "(with their per-medicine validation errors) plus a period summary. Use "
        "`date_from`/`date_to` to bound the window."
    ),
)
async def audit_report(
    ph_id: int = Path(..., description="medical_store_id"),
    date_from: datetime | None = Query(None, description="created_at >= (ISO 8601)"),
    date_to: datetime | None = Query(None, description="created_at <= (ISO 8601)"),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, ph_id)

    def _between(col):
        conds = []
        if date_from is not None:
            conds.append(col >= date_from)
        if date_to is not None:
            conds.append(col <= date_to)
        return conds

    # ── Parsing / processing failures ───────────────────────────────
    doc_filters = [Document.medical_store_id == ph_id, *_between(Document.created_at)]
    failed_docs = (
        await db.execute(
            select(Document)
            .where(*doc_filters, Document.status.in_(_FAILED_STATUSES))
            .order_by(Document.created_at.desc())
        )
    ).scalars().all()

    parsing_errors = [
        ParsingError(
            document_id=d.id,
            doc_key=d.doc_key,
            process_type=d.process_type,
            original_filename=d.original_filename,
            status=d.status,
            error_message=d.error_message,
            retry_count=d.retry_count,
            created_at=d.created_at,
        )
        for d in failed_docs
    ]

    # ── Force-saved dispense reports + per-row validation errors ─────
    rep_filters = [
        DrugReport.medical_store_id == ph_id,
        DrugReport.force_saved.is_(True),
        *_between(DrugReport.created_at),
    ]
    forced_reports = (
        await db.execute(
            select(DrugReport).where(*rep_filters).order_by(DrugReport.created_at.desc())
        )
    ).scalars().all()

    validation_errors: list[ValidationErrorRow] = []
    for rep in forced_reports:
        # `medicines` is lazy="selectin" so it's already loaded.
        for med in rep.medicines:
            if not med.has_errors:
                continue
            validation_errors.append(
                ValidationErrorRow(
                    report_id=rep.id,
                    document_id=rep.document_id,
                    report_from_date=rep.report_from_date,
                    report_to_date=rep.report_to_date,
                    medicine_id=med.id,
                    drug_name=med.drug_name,
                    ndc=med.ndc,
                    errors=med.validation_errors or [],
                    created_at=rep.created_at,
                )
            )

    # ── Summary counts ──────────────────────────────────────────────
    async def _count(stmt):
        return (await db.execute(stmt)).scalar() or 0

    act_base = [ActivityLog.medical_store_id == ph_id, *_between(ActivityLog.created_at)]

    documents_uploaded = await _count(
        select(func.count(ActivityLog.id)).where(
            *act_base, ActivityLog.action == "DOCUMENT_UPLOADED"
        )
    )
    invoices_saved = await _count(
        select(func.count(ActivityLog.id)).where(
            *act_base, ActivityLog.action == "INVOICE_SAVED"
        )
    )
    dispense_saved = await _count(
        select(func.count(DrugReport.id)).where(
            DrugReport.medical_store_id == ph_id, *_between(DrugReport.created_at)
        )
    )
    total_validation_errors = await _count(
        select(func.coalesce(func.sum(DrugReport.error_count), 0)).where(*rep_filters)
    )

    summary = AuditSummary(
        documents_uploaded=documents_uploaded,
        documents_failed=len(parsing_errors),
        dispense_reports_saved=dispense_saved,
        dispense_reports_force_saved=len(forced_reports),
        invoices_saved=invoices_saved,
        total_validation_errors=int(total_validation_errors),
    )

    return AuditReportResponse(
        medical_store_id=ph_id,
        date_from=date_from,
        date_to=date_to,
        summary=summary,
        parsing_errors=parsing_errors,
        validation_errors=validation_errors,
    )
