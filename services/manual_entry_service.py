"""
Service layer for **manual** data entry of invoices and dispense reports.

These functions accept validated Pydantic input schemas and persist the data
into the same DB tables used by the document-extraction pipeline.
"""

from __future__ import annotations

import json
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from models import (
    Dispense,
    DrugReport,
    Invoice,
    InvoiceLineItem,
    InvoiceSummary,
    Medicine,
)
from schemas.manual_dispense_input import (
    ManualDispenseReportInput,
    ManualDispenseReportCreatedOutput,
)
from schemas.manual_invoice_input import (
    ManualInvoiceInput,
    ManualInvoiceCreatedOutput,
)


# ---------------------------------------------------------------------------
# Invoice — manual entry
# ---------------------------------------------------------------------------

def store_manual_invoice(
    db: Session,
    payload: ManualInvoiceInput,
) -> ManualInvoiceCreatedOutput:
    """
    Persist a manually-entered invoice and its line items / summary.

    Returns a lightweight confirmation schema.
    """

    # Serialise the full input for auditability (stored as raw_payload)
    raw_payload = json.dumps(payload.model_dump(mode="json"), ensure_ascii=True)

    db_invoice = Invoice(
        source_filename="manual_entry",
        page_count=None,
        seller_name=payload.seller_name,
        seller_address=payload.seller_address,
        seller_phone=payload.seller_phone,
        seller_dea=payload.seller_dea,
        seller_permit=payload.seller_permit,
        seller_fed_id=payload.seller_fed_id,
        invoice_number=payload.invoice_number,
        invoice_date=payload.invoice_date,
        order_number=payload.order_number,
        due_date=payload.due_date,
        terms_of_payment=payload.terms_of_payment,
        your_order_number=payload.your_order_number,
        customer_number=payload.customer_number,
        customer_name=payload.customer_name,
        customer_dea=payload.customer_dea,
        customer_state_reg=payload.customer_state_reg,
        bill_to_name=payload.bill_to_name,
        bill_to_address=payload.bill_to_address,
        ship_to_name=payload.ship_to_name,
        ship_to_address=payload.ship_to_address,
        remit_to_name=payload.remit_to_name,
        remit_to_address=payload.remit_to_address,
        remit_to_phone=payload.remit_to_phone,
        raw_payload=raw_payload,
    )
    db.add(db_invoice)
    db.flush()

    for item in payload.line_items:
        # Auto-compute: no ndc11 + 4-digit UPC → verification not required
        upc_digits = (item.upc or "").strip()
        has_ndc11 = bool(item.ndc11 and item.ndc11.strip())
        is_short_upc = upc_digits.isdigit() and len(upc_digits) <= 4

        if not has_ndc11 and is_short_upc:
            verification_required = False
        else:
            verification_required = item.verification_required

        db_item = InvoiceLineItem(
            invoice_id=db_invoice.id,
            line=item.line,
            item_code=item.item_code,
            raw_ndc=item.raw_ndc,
            ndc11=item.ndc11,
            upc=item.upc,
            lot_number=item.lot_number,
            orig_order_qty=item.orig_order_qty,
            order_qty=item.order_qty,
            invoiced_qty=item.invoiced_qty,
            uom=item.uom,
            description=item.description,
            size=item.size,
            form=item.form,
            unit_price=item.unit_price,
            extended_price=item.extended_price,
            awp=item.awp,
            note_code=item.note_code,
            verification_required=verification_required,
            verified=item.verified,
            fda_package_ndc=item.fda_package_ndc,
            fda_ndc11=item.fda_ndc11,
            dm_gtin=item.dm_gtin,
            dm_serial_number=item.dm_serial_number,
            dm_expiration_date=item.dm_expiration_date,
            dm_lot_number=item.dm_lot_number,
        )
        db.add(db_item)

    if payload.summary:
        db_summary = InvoiceSummary(
            invoice_id=db_invoice.id,
            order_line_total=payload.summary.order_line_total,
            fuel_surcharge=payload.summary.fuel_surcharge,
            sub_total=payload.summary.sub_total,
            tax=payload.summary.tax,
            grand_total=payload.summary.grand_total,
            total_due_by=payload.summary.total_due_by,
        )
        db.add(db_summary)

    db.commit()
    db.refresh(db_invoice)

    logger.info(
        "Manual invoice stored: invoice_id={id} lines={lines}",
        id=db_invoice.id,
        lines=len(payload.line_items),
    )

    return ManualInvoiceCreatedOutput(
        invoice_id=db_invoice.id,
        line_items_created=len(payload.line_items),
    )


# ---------------------------------------------------------------------------
# Dispense report — manual entry
# ---------------------------------------------------------------------------

def store_manual_dispense_report(
    db: Session,
    payload: ManualDispenseReportInput,
) -> ManualDispenseReportCreatedOutput:
    """
    Persist a manually-entered dispense report with medicines and dispenses.

    Returns a lightweight confirmation schema.
    """

    db_report = DrugReport(
        pharmacy_name=payload.pharmacy_name,
        pharmacy_address=payload.pharmacy_address,
        pharmacy_phone=payload.pharmacy_phone,
        pharmacy_fax=payload.pharmacy_fax,
        report_date=payload.report_date,
        report_from_date=payload.report_from_date,
        report_to_date=payload.report_to_date,
        grand_total_rx_count=payload.grand_total_rx_count,
        grand_total_price=payload.grand_total_price,
        grand_total_cost=payload.grand_total_cost,
    )
    db.add(db_report)
    db.flush()

    total_dispenses = 0

    for med_input in payload.medicines:
        db_med = Medicine(
            report_id=db_report.id,
            drug_name=med_input.drug_name or "Unknown",
            ndc=med_input.ndc11,
            inventory_bucket=med_input.inventory_bucket,
            lot_no_exp_date=med_input.lot_no_exp_date,
            total_packs=med_input.total_packs,
            total_rx_count=med_input.total_rx_count,
            total_ins_paid=med_input.total_ins_paid,
            total_price=med_input.total_price,
            total_cost=med_input.total_cost,
        )
        db.add(db_med)
        db.flush()

        for disp_input in med_input.dispenses:
            db_disp = Dispense(
                medicine_id=db_med.id,
                qty_disp=disp_input.qty_disp,
                qty_ord=disp_input.qty_ord,
                days_supply=disp_input.days_supply,
                date_filled=disp_input.date_filled,
                rx_no=disp_input.rx_no,
                ref=disp_input.ref,
                pat_name=disp_input.pat_name,
                pat_addr=disp_input.pat_addr,
                pat_phone=disp_input.pat_phone,
                pres_name=disp_input.pres_name,
                pres_addr=disp_input.pres_addr,
                pres_phone=disp_input.pres_phone,
                price=disp_input.price,
                ins_paid=disp_input.ins_paid,
                ins_code=disp_input.ins_code,
            )
            db.add(db_disp)
            total_dispenses += 1

    db.commit()
    db.refresh(db_report)

    logger.info(
        "Manual dispense report stored: report_id={id} medicines={meds} dispenses={disps}",
        id=db_report.id,
        meds=len(payload.medicines),
        disps=total_dispenses,
    )

    return ManualDispenseReportCreatedOutput(
        report_id=db_report.id,
        medicines_created=len(payload.medicines),
        dispenses_created=total_dispenses,
    )
