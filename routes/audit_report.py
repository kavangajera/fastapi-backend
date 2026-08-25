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
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import DocumentStatus, Feature
from middlewares.auth import auth_incoming_req
from models import ActivityLog, Document, DrugReport
from schemas.audit_report import (
    AuditReportResponse,
    AuditSummary,
    ParsingError,
    ValidationErrorRow,
)
from schemas.response_schema import Response_Schema, success_response
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.audit_dismissal_service import (
    DISMISS_PARSING,
    DISMISS_VALIDATION,
    VALID_KINDS,
    dismiss,
    fetch_dismissed,
    restore,
)
from services.feature_gate import ensure_feature
from services.pharmacy_authz import ensure_pharmacy_access

router = APIRouter(tags=["Audit Report"])


class AuditDismissRequest(BaseModel):
    """Which audit rows to clear (or bring back).

    `kind` picks the section; `refs` are that section's identifiers —
    `doc_key`s for parsing failures, report ids (as strings) for validation
    rows. Both endpoints take a list so the UI's select-all is one call.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["parsing", "validation"]
    refs: list[str] = Field(..., min_length=1)

_FAILED_STATUSES = (DocumentStatus.FAILED.value, DocumentStatus.FAILED_PERMANENTLY.value)


@router.get(
    "/pharmacy/{ph_id}/audit-report",
    response_model=Response_Schema,
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
    include_dismissed: bool = Query(
        False, description="Also return entries the owner has cleared from this report"
    ),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, ph_id)
    await ensure_feature(db, ph_id, Feature.COMPLIANCE_REPORTS)

    # Entries the owner has cleared. The audit report is derived on every
    # request, so a cleared row can only be remembered separately — see
    # models/audit_dismissal. Live dismissals are filtered out below;
    # `include_dismissed` brings them back so they can be restored.
    # Always fetched: in the default view it filters cleared entries out, and
    # with include_dismissed it instead MARKS them, so the UI can badge them
    # and offer Restore on the cleared ones only.
    dismissed = await fetch_dismissed(db, ph_id)
    dismissed_docs = dismissed.get(DISMISS_PARSING, set())
    dismissed_reports = dismissed.get(DISMISS_VALIDATION, set())

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
            record_Identifier=d.record_Identifier,
            update_record_Identifier=d.update_record_Identifier,
            IsDeleted=d.IsDeleted,
            delete_date_at=d.delete_date_at,
            updated_at=d.updated_at,
            global_time_at=d.global_time_at,
            dismissed=d.doc_key in dismissed_docs,
        )
        for d in failed_docs
        if include_dismissed or d.doc_key not in dismissed_docs
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
        is_dismissed = str(rep.id) in dismissed_reports
        if is_dismissed and not include_dismissed:
            continue
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
                    record_Identifier=med.record_Identifier,
                    update_record_Identifier=med.update_record_Identifier,
                    IsDeleted=med.IsDeleted,
                    delete_date_at=med.delete_date_at,
                    updated_at=med.updated_at,
                    global_time_at=med.global_time_at,
                    dismissed=is_dismissed,
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

    return success_response(
        AuditReportResponse(
            medical_store_id=ph_id,
            date_from=date_from,
            date_to=date_to,
            summary=summary,
            parsing_errors=parsing_errors,
            validation_errors=validation_errors,
        ),
        "Audit report retrieved successfully",
    )


# ── Dismissals ──────────────────────────────────────────────────────────────

# Clearing an audit row must not destroy what it reports on: a parsing failure
# IS the document, a validation row IS the force-saved report, and both are the
# compliance record. So these endpoints record the dismissal and the GET above
# filters against it — the underlying rows are never touched.


@router.post(
    "/pharmacy/{ph_id}/audit-report/dismiss",
    response_model=Response_Schema,
    summary="Clear entries from the audit report (keeps the underlying records)",
    description=(
        "Hides the listed entries from `GET /pharmacy/{ph_id}/audit-report`. "
        "The documents and dispense reports behind them are left completely "
        "untouched, and `?include_dismissed=true` brings them back into view. "
        "Idempotent: clearing an already-cleared entry is a no-op."
    ),
)
async def dismiss_audit_entries(
    ph_id: int = Path(..., description="medical_store_id"),
    body: AuditDismissRequest = ...,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, ph_id)
    await ensure_feature(db, ph_id, Feature.COMPLIANCE_REPORTS)
    if body.kind not in VALID_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"status_code": 422, "message": f"Unknown kind '{body.kind}'", "data": None},
        )
    changed = await dismiss(
        db,
        medical_store_id=ph_id,
        kind=body.kind,
        refs=body.refs,
        user_id=user.user_id,
    )
    await db.commit()
    return success_response(
        {"kind": body.kind, "dismissed": changed, "requested": len(body.refs)},
        "Audit entries cleared successfully",
    )


@router.post(
    "/pharmacy/{ph_id}/audit-report/restore",
    response_model=Response_Schema,
    summary="Bring cleared entries back into the audit report",
)
async def restore_audit_entries(
    ph_id: int = Path(..., description="medical_store_id"),
    body: AuditDismissRequest = ...,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, ph_id)
    await ensure_feature(db, ph_id, Feature.COMPLIANCE_REPORTS)
    restored = await restore(db, medical_store_id=ph_id, kind=body.kind, refs=body.refs)
    await db.commit()
    return success_response(
        {"kind": body.kind, "restored": restored, "requested": len(body.refs)},
        "Audit entries restored successfully",
    )
