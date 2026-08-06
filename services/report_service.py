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


def compute_medicine_totals(dispenses: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive a medicine's totals by summing its own `dispenses` rows.

    The PDF/LLM-printed totals line is not trustworthy on its own (OCR
    misses, multi-page NDC blocks that only capture the first page's
    printed total, etc). A field missing on a given dispense is skipped
    rather than treated as zero — if every dispense in the group lacks
    that field, the summed total is None instead of 0.
    """

    def _sum(field: str) -> Decimal | None:
        total: Decimal | None = None
        for row in dispenses:
            value = _to_decimal(row.get(field))
            if value is None:
                continue
            total = value if total is None else total + value
        return total

    return {
        "total_quantity_dispensed": _sum("qty_disp"),
        "total_rx_count": len(dispenses) or None,
        "total_ins_paid": _sum("ins_paid"),
        "total_price": _sum("price"),
    }


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
        reference_number=disp_data.get("reference_number"),
        pat_name=disp_data.get("pat_name"),
        pat_addr=disp_data.get("pat_addr"),
        pat_phone=disp_data.get("pat_phone"),
        patient_dob=disp_data.get("patient_dob"),
        patient_gender=disp_data.get("patient_gender"),
        patient_id=disp_data.get("patient_id"),
        pres_name=disp_data.get("pres_name"),
        pres_addr=disp_data.get("pres_addr"),
        pres_phone=disp_data.get("pres_phone"),
        prescriber_dea=disp_data.get("prescriber_dea"),
        prescriber_npi=disp_data.get("prescriber_npi"),
        date_written=disp_data.get("date_written"),
        date_sold=disp_data.get("date_sold"),
        will_call_date=disp_data.get("will_call_date"),
        price=_to_decimal(disp_data.get("price")),
        ins_paid=_to_decimal(disp_data.get("ins_paid")),
        ins_code=disp_data.get("ins_code"),
        patient_copay=_to_decimal(disp_data.get("patient_copay")),
        cash_price=_to_decimal(disp_data.get("cash_price")),
        total_price=_to_decimal(disp_data.get("total_price")),
        source_page=_to_int(disp_data.get("source_page")),
        is_partial=bool(disp_data.get("is_partial", False)),
        extraction_warnings=disp_data.get("warnings") or None,
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
        pharmacy_name=pharmacy_meta.get("pharmacy_name") or None,
        pharmacy_address=pharmacy_meta.get("address") or None,
        pharmacy_phone=pharmacy_meta.get("phone") or None,
        pharmacy_fax=pharmacy_meta.get("fax") or None,
        grand_total_rx_count=_to_int(grand_total.get("total_rx_count")),
        grand_total_price=_to_decimal(grand_total.get("total_price")),
        grand_total_cost=_to_decimal(grand_total.get("total_cost")),
        grand_total_ins_paid=_to_decimal(grand_total.get("total_ins_paid")),
    )
    db.add(db_report)
    await db.flush()

    total_dispenses = 0
    for med_data in medicines:
        totals = med_data.get("totals", {})
        dispenses = med_data.get("dispenses", [])
        computed = compute_medicine_totals(dispenses)
        db_med = Medicine(
            report_id=db_report.id,
            drug_name=med_data["drug_name"],
            ndc=med_data["ndc"],
            inventory_bucket=med_data.get("inventory_bucket"),
            lot_no_exp_date=med_data.get("lot_no_exp_date"),
            lot_number=med_data.get("lot_number"),
            expiration_date=med_data.get("expiration_date"),
            pack_size=med_data.get("pack_size"),
            manufacturer=med_data.get("manufacturer"),
            generic_indicator=med_data.get("generic_indicator"),
            strength=med_data.get("strength"),
            daw_code=med_data.get("daw_code"),
            drug_schedule=med_data.get("drug_schedule"),
            total_packs=_to_decimal(totals.get("packs")),
            total_quantity_dispensed=computed["total_quantity_dispensed"],
            total_rx_count=computed["total_rx_count"],
            total_ins_paid=computed["total_ins_paid"],
            total_price=computed["total_price"],
            total_cost=_to_decimal(totals.get("total_cost")),
        )
        db.add(db_med)
        await db.flush()

        for disp_data in dispenses:
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
