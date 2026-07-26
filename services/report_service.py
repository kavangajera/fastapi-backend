"""
services/report_service.py
──────────────────────────
Async persistence for a parsed dispense report.

`reconcile_batch` (the cross-document quantity comparison) lives in
`services/reconciliation_service.py` and is called explicitly by the
reconciliation route after every batch member has finished — it is
intentionally NOT triggered here so a single dispense upload doesn't
implicitly reconcile against an unrelated invoice.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from models import Dispense, DrugReport, Medicine


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


def _build_dispense(disp_data: dict, medicine_id: int, medical_store_id: int) -> Dispense:
    return Dispense(
        medicine_id=medicine_id,
        medical_store_id=medical_store_id,
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


async def store_report(
    db: AsyncSession,
    report_data: dict[str, Any],
    *,
    medical_store_id: int,
    document_id: int | None = None,
    batch_id: int | None = None,
) -> dict[str, Any]:
    """Persist a parsed DrugReport + Medicines + Dispenses (no reconciliation)."""
    pharmacy_meta = report_data.get("pharmacy", {})
    grand_total = report_data.get("grand_total", {})
    medicines = report_data.get("medicines", [])

    db_report = DrugReport(
        medical_store_id=medical_store_id,
        document_id=document_id,
        batch_id=batch_id,
        report_date=pharmacy_meta.get("report_date") or None,
        report_from_date=pharmacy_meta.get("report_from_date") or None,
        report_to_date=pharmacy_meta.get("report_to_date") or None,
        grand_total_rx_count=_to_int(grand_total.get("total_rx_count")),
        grand_total_price=_to_decimal(grand_total.get("total_price")),
        grand_total_cost=_to_decimal(grand_total.get("total_cost")),
    )
    db.add(db_report)
    await db.flush()

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
        await db.flush()

        for disp_data in med_data.get("dispenses", []):
            db.add(_build_dispense(disp_data, db_med.id, medical_store_id))
            total_dispenses += 1

    await db.flush()

    logger.info(
        "Stored dispense report: report_id={rid} medical_store_id={ph} medicines={m} dispenses={d}",
        rid=db_report.id,
        ph=medical_store_id,
        m=len(medicines),
        d=total_dispenses,
    )

    return {
        "report_id": db_report.id,
        "medical_store_id": medical_store_id,
        "report_from_date": db_report.report_from_date,
        "report_to_date": db_report.report_to_date,
        "medicines_saved": len(medicines),
        "dispenses_saved": total_dispenses,
        "grand_total_rx_count": db_report.grand_total_rx_count,
        "grand_total_price": (
            str(db_report.grand_total_price) if db_report.grand_total_price is not None else None
        ),
    }
