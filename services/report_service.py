"""
services/report_service.py
──────────────────────────
Persistence for extracted drug-dispense reports.

This mirrors the storage logic in ``routes/pharmacy_purchase_report.py``
so the Kafka dispense worker can persist a report WITHOUT going through
the HTTP route. The route is intentionally left untouched.

Input is the standard report dict produced by
``services.document_extractor.extract_report_from_file``:
    { "pharmacy": {...}, "grand_total": {...}, "medicines": [...] }
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    DrugReport,
    Medicine,
    Dispense,
    InvoiceLineItem,
    DispenseReconciliation,
)


# ── helpers (kept consistent with the route) ─────────────────────────────────

def _to_decimal(value: Any | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        return None


def _to_int(value: Any | None) -> int | None:
    if not value:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


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
        medicine_id=medicine.id,  # re-set after flush
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


def store_report(db: Session, report_data: dict[str, Any]) -> dict[str, Any]:
    """
    Persist a parsed report (DrugReport + Medicines + Dispenses) and build
    its DispenseReconciliation rows. Commits the session.

    Returns a lightweight summary dict suitable for the result payload.
    """
    pharmacy = report_data["pharmacy"]
    grand_total = report_data["grand_total"]
    medicines = report_data["medicines"]

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

    for med_data in medicines:
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
        db.flush()

        dispenses = [
            _build_dispense(disp_data, db_med)
            for disp_data in med_data.get("dispenses", [])
        ]
        if dispenses:
            for disp in dispenses:
                disp.medicine_id = db_med.id
            db.bulk_save_objects(dispenses)
            total_dispenses += len(dispenses)

    db.commit()
    db.refresh(db_report)

    # ── Reconciliation: invoice qty vs dispensed qty per code ────────
    report_codes: set[str] = set()
    for med in medicines:
        ndc = str(med.get("ndc")) if med.get("ndc") else None
        if ndc:
            report_codes.add(ndc)

    invoice_upcs = (
        db.query(InvoiceLineItem.upc)
        .filter(InvoiceLineItem.upc != None)  # noqa: E711
        .distinct()
        .all()
    )
    for (upc,) in invoice_upcs:
        if upc and upc not in report_codes:
            report_codes.add(upc)

    for code in report_codes:
        dispensed_qty = (
            db.query(func.sum(Dispense.qty_disp))
            .join(Medicine, Medicine.id == Dispense.medicine_id)
            .filter(Medicine.report_id == db_report.id, Medicine.ndc == code)
            .scalar()
        )
        invoice_items = (
            db.query(InvoiceLineItem)
            .filter(
                (InvoiceLineItem.ndc11 == code) | (InvoiceLineItem.upc == code)
            )
            .all()
        )
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
        "Report stored (worker): report_id={report_id} medicines={med} dispenses={disp}",
        report_id=db_report.id,
        med=len(medicines),
        disp=total_dispenses,
    )

    return {
        "report_id": db_report.id,
        "pharmacy_name": db_report.pharmacy_name,
        "report_from_date": db_report.report_from_date,
        "report_to_date": db_report.report_to_date,
        "medicines_saved": len(medicines),
        "dispenses_saved": total_dispenses,
        "grand_total_rx_count": db_report.grand_total_rx_count,
        "grand_total_price": (
            str(db_report.grand_total_price)
            if db_report.grand_total_price is not None
            else None
        ),
    }
