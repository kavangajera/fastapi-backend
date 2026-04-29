"""
routes/report.py
────────────────
FastAPI router for Drug Dispensed Report operations.

Endpoints
---------
POST /reports/upload          Upload a PDF → extract → store → confirmation JSON
GET  /reports/                List all reports (lightweight)
GET  /reports/{report_id}     Full report with all medicines + dispenses
GET  /reports/{report_id}/medicines/{ndc}   All dispenses for one NDC
DELETE /reports/{report_id}   Delete a report and all its children
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session, selectinload

from database import get_db
from models import DrugReport, Medicine, Dispense
from schemas.pharmacy_purchase_report import (
    DrugReportListItem,
    DrugReportResponse,
    MedicineResponse,
    UploadSummary,
)
from services.pdf_extractor import extract_report

router = APIRouter(prefix="/reports", tags=["Drug Dispensed Reports"])


# ── helpers ──────────────────────────────────────────────────────────────────

def _to_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        return None


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _build_dispense(disp_data: dict, medicine: Medicine) -> Dispense:
    return Dispense(
        medicine_id=medicine.id,  # set after flush
        qty_disp=_to_decimal(disp_data.get("qty_disp")),
        qty_ord=_to_decimal(disp_data.get("qty_ord")),
        days_supply=_to_int(disp_data.get("days_supply")),
        date_filled=disp_data.get("date_filled"),
        rx_no=disp_data.get("rx_no"),
        ref=disp_data.get("ref"),
        pat_name=disp_data.get("pat_name"),
        pat_addr=disp_data.get("pat_addr"),
        pat_phone=disp_data.get("pat_phone"),
        pres_name=disp_data.get("pres_name"),
        pres_addr=disp_data.get("pres_addr"),
        pres_phone=disp_data.get("pres_phone"),
        price=_to_decimal(disp_data.get("price")),
        ins_paid=_to_decimal(disp_data.get("ins_paid")),
        ins_code=disp_data.get("ins_code"),
    )


# ── POST /reports/upload ─────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=UploadSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a Drug Dispensed Report PDF",
    description=(
        "Upload a text-based PDF exported from the pharmacy system. "
        "The service extracts all prescription data and stores it in the database. "
        "Returns a confirmation summary with counts and totals."
    ),
)
async def upload_report(
    file: UploadFile = File(..., description="Drug Dispensed Report PDF (text-based)"),
    db: Session = Depends(get_db),
):
    # ── validate file type ────────────────────────────────────────────────────
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted. Please upload a .pdf file.",
        )

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # ── extract data from PDF ─────────────────────────────────────────────────
    try:
        report_data = extract_report(pdf_bytes)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"PDF extraction failed: {exc}",
        )

    pharmacy = report_data["pharmacy"]
    grand_total = report_data["grand_total"]

    # ── create DrugReport row ─────────────────────────────────────────────────
    db_report = DrugReport(
        pharmacy_name=pharmacy.get("pharmacy_name") or None,
        pharmacy_address=pharmacy.get("address") or None,
        pharmacy_phone=pharmacy.get("phone") or None,
        pharmacy_fax=pharmacy.get("fax") or None,
        report_date=pharmacy.get("report_date") or None,
        report_from_date=pharmacy.get("report_from_date") or None,
        report_to_date=pharmacy.get("report_to_date") or None,
        grand_total_rx_count=_to_int(grand_total.get("total_rx_count")),
        grand_total_price=_to_decimal(grand_total.get("total_price")),
        grand_total_cost=_to_decimal(grand_total.get("total_cost")),
    )
    db.add(db_report)
    db.flush()  # get db_report.id

    # ── create Medicine + Dispense rows ───────────────────────────────────────
    total_dispenses = 0

    for med_data in report_data["medicines"]:
        totals = med_data.get("totals", {})
        db_med = Medicine(
            report_id=db_report.id,
            drug_name=med_data["drug_name"],
            ndc=med_data["ndc"],
            inventory_bucket=med_data.get("inventory_bucket"),
            lot_no_exp_date=med_data.get("lot_no_exp_date"),
            total_packs=_to_decimal(totals.get("packs")),
            total_rx_count=_to_int(totals.get("total_rx_count")),
            total_ins_paid=_to_decimal(totals.get("total_ins_paid")),
            total_price=_to_decimal(totals.get("total_price")),
            total_cost=_to_decimal(totals.get("total_cost")),
        )
        db.add(db_med)
        db.flush()  # get db_med.id

        for disp_data in med_data.get("dispenses", []):
            db_disp = _build_dispense(disp_data, db_med)
            db_disp.medicine_id = db_med.id
            db.add(db_disp)
            total_dispenses += 1

    db.commit()
    db.refresh(db_report)

    return UploadSummary(
        report_id=db_report.id,
        pharmacy_name=db_report.pharmacy_name,
        report_from_date=db_report.report_from_date,
        report_to_date=db_report.report_to_date,
        medicines_saved=len(report_data["medicines"]),
        dispenses_saved=total_dispenses,
        grand_total_rx_count=db_report.grand_total_rx_count,
        grand_total_price=db_report.grand_total_price,
        message="PDF processed and stored successfully.",
    )


# ── GET /reports/ ─────────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=List[DrugReportListItem],
    summary="List all uploaded reports",
)
def list_reports(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    reports = (
        db.query(DrugReport)
        .order_by(DrugReport.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return reports


# ── GET /reports/{report_id} ──────────────────────────────────────────────────

@router.get(
    "/{report_id}",
    response_model=DrugReportResponse,
    summary="Get a full report with all medicines and dispenses",
)
def get_report(report_id: int, db: Session = Depends(get_db)):
    report = (
        db.query(DrugReport)
        .options(
            selectinload(DrugReport.medicines).selectinload(Medicine.dispenses)
        )
        .filter(DrugReport.id == report_id)
        .first()
    )
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report {report_id} not found.",
        )
    return report


# ── GET /reports/{report_id}/medicines/{ndc} ──────────────────────────────────

@router.get(
    "/{report_id}/medicines/{ndc}",
    response_model=MedicineResponse,
    summary="Get a specific medicine (by NDC) within a report",
)
def get_medicine_by_ndc(report_id: int, ndc: str, db: Session = Depends(get_db)):
    med = (
        db.query(Medicine)
        .options(selectinload(Medicine.dispenses))
        .filter(Medicine.report_id == report_id, Medicine.ndc == ndc)
        .first()
    )
    if not med:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Medicine with NDC {ndc} not found in report {report_id}.",
        )
    return med


# ── DELETE /reports/{report_id} ───────────────────────────────────────────────

@router.delete(
    "/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a report and all its associated data",
)
def delete_report(report_id: int, db: Session = Depends(get_db)):
    report = db.query(DrugReport).filter(DrugReport.id == report_id).first()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report {report_id} not found.",
        )
    db.delete(report)
    db.commit()