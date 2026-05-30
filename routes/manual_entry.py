"""
routes/manual_entry.py
──────────────────────
FastAPI router for **manual** data entry of invoices and dispense reports.

Endpoints
---------
POST /manual/invoice     Create an invoice from JSON input
POST /manual/dispense    Create a dispense report from JSON input
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy.orm import Session

from database import get_db
from schemas.manual_invoice_input import ManualInvoiceInput, ManualInvoiceCreatedOutput
from schemas.manual_dispense_input import ManualDispenseReportInput, ManualDispenseReportCreatedOutput
from services.manual_entry_service import store_manual_invoice, store_manual_dispense_report

router = APIRouter(prefix="/manual", tags=["Manual Data Entry"])


# ── POST /manual/invoice ────────────────────────────────────────────────────

@router.post(
    "/invoice",
    response_model=ManualInvoiceCreatedOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Manually enter invoice data",
    description=(
        "Create an invoice record from a strict JSON payload instead of uploading a PDF. "
        "Each line item **requires** `ndc11` (11-digit NDC) and `invoiced_qty`. "
        "All other fields are optional."
    ),
)
def create_manual_invoice(
    payload: ManualInvoiceInput,
    db: Session = Depends(get_db),
):
    try:
        result = store_manual_invoice(db, payload)
    except Exception as exc:
        logger.exception("Manual invoice creation failed: {error}", error=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store manual invoice: {exc}",
        )
    return result


# ── POST /manual/dispense ───────────────────────────────────────────────────

@router.post(
    "/dispense",
    response_model=ManualDispenseReportCreatedOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Manually enter dispense (purchase report) data",
    description=(
        "Create a dispense report record from a strict JSON payload instead of uploading a document. "
        "Each medicine entry **requires** `ndc11` (11-digit NDC). "
        "Each dispense line **requires** `qty_disp` (quantity dispensed). "
        "All other fields are optional."
    ),
)
def create_manual_dispense_report(
    payload: ManualDispenseReportInput,
    db: Session = Depends(get_db),
):
    try:
        result = store_manual_dispense_report(db, payload)
    except Exception as exc:
        logger.exception("Manual dispense report creation failed: {error}", error=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store manual dispense report: {exc}",
        )
    return result
