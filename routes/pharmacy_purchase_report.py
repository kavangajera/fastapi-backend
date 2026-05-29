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

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import os
import sys
from typing import List, Iterator, Iterable
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func
from loguru import logger
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from core.config import settings
from database import get_db
from models import DrugReport, Medicine, Dispense, InvoiceLineItem, DispenseReconciliation
from schemas.pharmacy_purchase_report import (
    DrugReportListItem,
    DrugReportResponse,
    MedicineResponse,
    UploadSummary,
    UploadBatchSummary,
)
from services.document_extractor import extract_report_from_file, SUPPORTED_EXTENSIONS

router = APIRouter(prefix="/reports", tags=["Drug Dispensed Reports"])


@contextmanager
def _progress_tracker(enabled: bool) -> Iterator[Progress | None]:
    if not enabled:
        yield None
        return
    progress = Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        transient=True,
    )
    with progress:
        yield progress


def _progress_enabled() -> bool:
    if os.getenv("ENABLE_PROGRESS", "1") == "0":
        return False
    return sys.stderr.isatty()


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


def _missing_fields(payload: dict, keys: Iterable[str]) -> list[str]:
    missing = []
    for key in keys:
        value = payload.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(key)
    return missing


def _sum_invoice_qty(items: list[InvoiceLineItem]) -> Decimal | None:
    total = Decimal("0")
    has_value = False
    for item in items:
        qty = _to_decimal(item.invoiced_qty)
        if qty is None:
            continue
        total += qty
        has_value = True
    return total if has_value else None


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
    response_model=UploadBatchSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a Drug Dispensed Report (PDF / DOCX / DOC / XLSX / XLS)",
    description=(
        "Upload a Drug Dispensed Report exported from the pharmacy system. "
        "Accepted formats: .pdf (text-based), .docx, .doc (RTF), .xlsx, and .xls. "
        "The service extracts all prescription data and stores it in the database. "
        "Returns a confirmation summary with counts and totals."
    ),
)
async def upload_report(
    files: List[UploadFile] = File(..., description="Up to 10 reports (.pdf, .docx, .doc, .xlsx, or .xls)"),
    db: Session = Depends(get_db),
):
    if len(files) > settings.REPORT_MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Max {settings.REPORT_MAX_FILES} reports allowed per request.",
        )

    summaries: List[UploadSummary] = []

    for file in files:
        _ext = (file.filename or "").lower().rsplit(".", 1)[-1] if file.filename and "." in file.filename else ""
        if not file.filename or _ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Unsupported file type. Please upload one of: "
                    f"{', '.join(f'.{e}' for e in sorted(SUPPORTED_EXTENSIONS))}."
                ),
            )

        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        logger.info("Report upload started: {filename} ({size} bytes)", filename=file.filename, size=len(file_bytes))

        with _progress_tracker(_progress_enabled()) as progress:
            extract_task_id = None
            if progress:
                extract_task_id = progress.add_task(f"Extracting {_ext.upper()}", total=1)
            try:
                report_data = extract_report_from_file(file_bytes, file.filename)
            except Exception as exc:
                logger.exception("Report extraction failed")
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Report extraction failed: {exc}",
                )
            if progress and extract_task_id is not None:
                progress.advance(extract_task_id, 1)

        pharmacy = report_data["pharmacy"]
        grand_total = report_data["grand_total"]

        total_medicines = len(report_data["medicines"])
        total_dispenses_expected = sum(
            len(med.get("dispenses", [])) for med in report_data["medicines"]
        )
        logger.info(
            "Parsed report: medicines={med_count}, dispenses={disp_count}",
            med_count=total_medicines,
            disp_count=total_dispenses_expected,
        )

        header_missing = _missing_fields(pharmacy, pharmacy.keys())
        totals_missing = _missing_fields(grand_total, grand_total.keys())
        logger.info(
            "Report header extracted: missing={missing}",
            missing=header_missing,
        )
        logger.info(
            "Report grand totals extracted: missing={missing}",
            missing=totals_missing,
        )

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
        db.flush()

        total_dispenses = 0
        progress_total = total_dispenses_expected or total_medicines or 1

        with _progress_tracker(_progress_enabled()) as progress:
            save_task_id = None
            if progress:
                save_task_id = progress.add_task("Saving to DB", total=progress_total)

            for med_data in report_data["medicines"]:
                totals = med_data.get("totals", {})
                med_missing = _missing_fields(med_data, med_data.keys())
                totals_missing = _missing_fields(totals, totals.keys())
                logger.info(
                    "Medicine extracted: ndc={ndc} name={name} missing={missing} totals_missing={totals_missing}",
                    ndc=med_data.get("ndc"),
                    name=med_data.get("drug_name"),
                    missing=med_missing,
                    totals_missing=totals_missing,
                )
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
                db.flush()

                dispenses = [
                    _build_dispense(disp_data, db_med)
                    for disp_data in med_data.get("dispenses", [])
                ]
                if dispenses:
                    for idx, disp_data in enumerate(med_data.get("dispenses", []), start=1):
                        disp_missing = _missing_fields(disp_data, disp_data.keys())
                        logger.info(
                            "Dispense extracted: ndc={ndc} rx_no={rx} missing={missing}",
                            ndc=med_data.get("ndc"),
                            rx=disp_data.get("rx_no"),
                            missing=disp_missing,
                        )
                    for disp in dispenses:
                        disp.medicine_id = db_med.id
                    db.bulk_save_objects(dispenses)
                    total_dispenses += len(dispenses)
                    if progress and save_task_id is not None:
                        progress.advance(save_task_id, len(dispenses))
                elif progress and save_task_id is not None and total_dispenses_expected == 0:
                    progress.advance(save_task_id, 1)

        db.commit()
        db.refresh(db_report)


        # Collect all unique ndc and upc codes from medicines
        report_codes = set()
        for med in report_data["medicines"]:
            ndc = str(med.get("ndc")) if med.get("ndc") else None
            if ndc:
                report_codes.add(ndc)

        # Also add all unique UPCs from InvoiceLineItem that are not in ndc11
        invoice_upcs = db.query(InvoiceLineItem.upc).filter(InvoiceLineItem.upc != None).distinct().all()
        for (upc,) in invoice_upcs:
            if upc and upc not in report_codes:
                report_codes.add(upc)

        for code in report_codes:
            # Try to match by ndc11 first, then by upc if not found
            dispensed_qty = (
                db.query(func.sum(Dispense.qty_disp))
                .join(Medicine, Medicine.id == Dispense.medicine_id)
                .filter(Medicine.report_id == db_report.id, Medicine.ndc == code)
                .scalar()
            )

            # Prefer ndc11 match, fallback to upc
            invoice_items = db.query(InvoiceLineItem).filter(
                (InvoiceLineItem.ndc11 == code) | (InvoiceLineItem.upc == code)
            ).all()
            invoice_qty = _sum_invoice_qty(invoice_items)

            remaining_qty = None
            if invoice_qty is not None and dispensed_qty is not None:
                remaining_qty = invoice_qty - dispensed_qty

            db.add(
                DispenseReconciliation(
                    report_id=db_report.id,
                    ndc11=code,
                    invoice_qty=invoice_qty,
                    dispensed_qty=dispensed_qty,
                    remaining_qty=remaining_qty,
                )
            )

        db.commit()

        logger.info(
            "Report stored: report_id={report_id}, medicines={med_count}, dispenses={disp_count}",
            report_id=db_report.id,
            med_count=total_medicines,
            disp_count=total_dispenses,
        )

        summaries.append(
            UploadSummary(
                report_id=db_report.id,
                pharmacy_name=db_report.pharmacy_name,
                report_from_date=db_report.report_from_date,
                report_to_date=db_report.report_to_date,
                medicines_saved=len(report_data["medicines"]),
                dispenses_saved=total_dispenses,
                grand_total_rx_count=db_report.grand_total_rx_count,
                grand_total_price=db_report.grand_total_price,
                message=f"{_ext.upper()} processed and stored successfully.",
            )
        )

    return UploadBatchSummary(reports=summaries)


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
    "/{report_id:int}",
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
    "/{report_id:int}/medicines/{ndc}",
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
    "/{report_id:int}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a report and all its associated data",
)
def delete_report(report_id: int, db: Session = Depends(get_db)):
    deleted_count = db.query(DrugReport).filter(DrugReport.id == report_id).delete(synchronize_session=False)
    if deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report {report_id} not found.",
        )
    db.commit()


# ── DELETE /reports/clear ────────────────────────────────────────────────────

@router.delete(
    "/clear-all",
    summary="Delete all parsed report data",
)
def clear_all_reports(
    confirm: bool = False,
    db: Session = Depends(get_db),
):
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set confirm=true to delete all report data.",
        )

    deleted_reports = db.query(DrugReport).count()
    if deleted_reports == 0:
        return {
            "deleted_reports": 0,
            "message": "No report data to delete.",
        }

    db.query(DrugReport).delete(synchronize_session=False)
    db.commit()

    logger.warning("Cleared all report data (reports={count})", count=deleted_reports)

    return {
        "deleted_reports": deleted_reports,
        "message": "All report data deleted.",
    }


# ── GET /reports/pdf ───────────────────────────────────────────────────────

@router.get(
    "/pdf",
    summary="Download a daily report PDF",
)
def download_report_pdf(
    date: str,
    db: Session = Depends(get_db),
):
    reports = (
        db.query(DrugReport)
        .options(selectinload(DrugReport.medicines).selectinload(Medicine.dispenses))
        .filter(DrugReport.report_date == date)
        .all()
    )
    if not reports:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No reports found for date {date}.",
        )

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 40

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, f"Dispense Report Summary - {date}")
    y -= 30

    for report in reports:
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(40, y, f"Pharmacy: {report.pharmacy_name or 'N/A'}")
        y -= 16
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"Report Range: {report.report_from_date or '-'} to {report.report_to_date or '-'}")
        y -= 16

        reconciliations = (
            db.query(DispenseReconciliation)
            .filter(DispenseReconciliation.report_id == report.id)
            .all()
        )
        recon_by_ndc = {rec.ndc11: rec for rec in reconciliations}

        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(40, y, "NDC11")
        pdf.drawString(140, y, "Drug")
        pdf.drawString(320, y, "Verified")
        pdf.drawString(380, y, "Dispensed")
        pdf.drawString(450, y, "Invoice")
        pdf.drawString(520, y, "Remain")
        y -= 12

        pdf.setFont("Helvetica", 9)
        for med in report.medicines:
            recon = recon_by_ndc.get(med.ndc)
            disp_qty = recon.dispensed_qty if recon else None
            inv_qty = recon.invoice_qty if recon else None
            rem_qty = recon.remaining_qty if recon else None

            invoice_items = (
                db.query(InvoiceLineItem)
                .filter(InvoiceLineItem.ndc11 == med.ndc)
                .all()
            )
            if not invoice_items:
                verification_status = "No invoice"
            elif any(not item.verification_required for item in invoice_items):
                verification_status = "Not required"
            elif any(item.dm_serial_number or item.dm_gtin for item in invoice_items):
                verification_status = "Verified"
            else:
                verification_status = "Pending"

            pdf.drawString(40, y, med.ndc)
            pdf.drawString(140, y, (med.drug_name or "-")[:26])
            pdf.drawString(320, y, verification_status)
            pdf.drawRightString(430, y, str(disp_qty) if disp_qty is not None else "-")
            pdf.drawRightString(500, y, str(inv_qty) if inv_qty is not None else "-")
            pdf.drawRightString(570, y, str(rem_qty) if rem_qty is not None else "-")
            y -= 12

            if y < 60:
                pdf.showPage()
                y = height - 40
                pdf.setFont("Helvetica", 9)

        y -= 10
        if y < 80:
            pdf.showPage()
            y = height - 40

    pdf.save()
    buffer.seek(0)

    filename = f"dispense-report-{date}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )