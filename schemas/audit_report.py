"""
schemas/audit_report.py
───────────────────────
Response models for `GET /pharmacy/{ph_id}/audit-report` — an audit-friendly
view that surfaces every error encountered while parsing or storing documents,
plus a period summary.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents_uploaded: int = 0
    documents_failed: int = 0
    dispense_reports_saved: int = 0
    dispense_reports_force_saved: int = 0
    invoices_saved: int = 0
    total_validation_errors: int = 0


class ParsingError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: int
    doc_key: str
    process_type: str
    original_filename: str | None = None
    status: str
    error_message: str | None = None
    retry_count: int
    created_at: datetime


class ValidationErrorRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: int
    document_id: int | None = None
    report_from_date: str | None = None
    report_to_date: str | None = None
    medicine_id: int
    drug_name: str
    ndc: str
    errors: list[dict] = []
    created_at: datetime


class AuditReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medical_store_id: int
    date_from: datetime | None = None
    date_to: datetime | None = None
    summary: AuditSummary
    parsing_errors: list[ParsingError]
    validation_errors: list[ValidationErrorRow]
