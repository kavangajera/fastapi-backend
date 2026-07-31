from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable

import fitz
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from models import Invoice, InvoiceLineItem, InvoiceSummary
from services.invoice_extractor import InvoiceParser
from services.ndc_utils import digits_only, ndc10_to_ndc11_from_package_ndc


def count_pdf_pages(file_bytes: bytes) -> int:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        return len(doc)
    finally:
        doc.close()


def _classify_ndc(raw_ndc: str | None) -> tuple[str | None, str | None, bool]:
    if not raw_ndc:
        return None, None, False

    cleaned = digits_only(raw_ndc)
    if not cleaned:
        return None, None, False

    if len(cleaned) <= 5:
        return None, cleaned, False

    if len(cleaned) == 11:
        return cleaned, None, True

    if len(cleaned) == 10 and "-" in raw_ndc:
        ndc11 = ndc10_to_ndc11_from_package_ndc(raw_ndc)
        return ndc11, None, True

    return None, None, True


def _missing_fields(payload: dict, keys: Iterable[str]) -> list[str]:
    missing = []
    for key in keys:
        value = payload.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(key)
    return missing


def _log_invoice_payload(invoice_payload) -> None:
    header = invoice_payload.model_dump(exclude={"line_items", "summary"})
    header_missing = _missing_fields(header, header.keys())
    logger.info(
        "Invoice header extracted: fields={fields} missing={missing}",
        fields=sorted(header.keys()),
        missing=header_missing,
    )

    if invoice_payload.summary:
        summary_payload = invoice_payload.summary.model_dump()
        summary_missing = _missing_fields(summary_payload, summary_payload.keys())
        logger.info(
            "Invoice summary extracted: fields={fields} missing={missing}",
            fields=sorted(summary_payload.keys()),
            missing=summary_missing,
        )
    else:
        logger.info("Invoice summary extracted: none")

    for idx, item in enumerate(invoice_payload.line_items, start=1):
        item_payload = item.model_dump()
        missing = _missing_fields(item_payload, item_payload.keys())
        logger.info(
            "Line item {idx} extracted: ndc={ndc} item_code={code} missing={missing}",
            idx=idx,
            ndc=item_payload.get("ndc"),
            code=item_payload.get("item_code"),
            missing=missing,
        )


def extract_invoice_from_pdf(file_bytes: bytes, filename: str):
    """SYNC — runs the OCR / LLM pipeline. Callers should wrap in asyncio.to_thread."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(file_bytes)
        tmp.flush()

        parser = InvoiceParser()
        invoice_payload = parser.parse(tmp.name)
        _log_invoice_payload(invoice_payload)
        return invoice_payload


async def store_invoice(
    db: AsyncSession,
    invoice_payload,
    *,
    source_filename: str,
    page_count: int,
    medical_store_id: int,
    document_id: int | None = None,
    batch_id: int | None = None,
) -> Invoice:
    raw_payload = json.dumps(invoice_payload.model_dump(), ensure_ascii=True)

    db_invoice = Invoice(
        medical_store_id=medical_store_id,
        document_id=document_id,
        batch_id=batch_id,
        source_filename=source_filename,
        page_count=page_count,
        seller_name=invoice_payload.seller_name,
        seller_address=invoice_payload.seller_address,
        seller_phone=invoice_payload.seller_phone,
        seller_dea=invoice_payload.seller_dea,
        seller_permit=invoice_payload.seller_permit,
        seller_fed_id=invoice_payload.seller_fed_id,
        invoice_number=invoice_payload.invoice_number,
        invoice_date=invoice_payload.invoice_date,
        order_number=invoice_payload.order_number,
        due_date=invoice_payload.due_date,
        terms_of_payment=invoice_payload.terms_of_payment,
        your_order_number=invoice_payload.your_order_number,
        customer_number=invoice_payload.customer_number,
        customer_name=invoice_payload.customer_name,
        customer_dea=invoice_payload.customer_dea,
        customer_state_reg=invoice_payload.customer_state_reg,
        bill_to_name=invoice_payload.bill_to_name,
        bill_to_address=invoice_payload.bill_to_address,
        ship_to_name=invoice_payload.ship_to_name,
        ship_to_address=invoice_payload.ship_to_address,
        remit_to_name=invoice_payload.remit_to_name,
        remit_to_address=invoice_payload.remit_to_address,
        remit_to_phone=invoice_payload.remit_to_phone,
        raw_payload=raw_payload,
    )
    db.add(db_invoice)
    await db.flush()

    for item in invoice_payload.line_items:
        ndc11, upc, verification_required = _classify_ndc(item.ndc)
        db.add(
            InvoiceLineItem(
                invoice_id=db_invoice.id,
                line=item.line,
                item_code=item.item_code,
                raw_ndc=item.ndc,
                ndc11=ndc11,
                upc=upc,
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
            )
        )

    summary = invoice_payload.summary or None
    if summary:
        db.add(
            InvoiceSummary(
                invoice_id=db_invoice.id,
                order_line_total=summary.order_line_total,
                fuel_surcharge=summary.fuel_surcharge,
                sub_total=summary.sub_total,
                tax=summary.tax,
                grand_total=summary.grand_total,
                total_due_by=summary.total_due_by,
            )
        )

    logger.info(
        "Stored invoice: filename={filename} lines={lines} medical_store_id={ph}",
        filename=source_filename,
        lines=len(invoice_payload.line_items),
        ph=medical_store_id,
    )

    return db_invoice
