"""
routes/invoice_save.py
──────────────────────
`POST /invoices` — persist a (possibly user-edited) invoice JSON and
apply +qty per line item to `medicine_inventory`.

The request body shape mirrors what `/documents/process?process_type=invoice`
returned, plus optional per-line-item barcode/datamatrix fields the user
may have spliced in from `/documents/process?process_type=barcode`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from middlewares.auth import auth_incoming_req
from models import Invoice, InvoiceLineItem, InvoiceSummary
from schemas.save_invoice import (
    InventoryUpdate,
    InvoiceLineItemInput,
    InvoiceSaveRequest,
    InvoiceSaveResponse,
)
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.inventory_service import add_invoice_quantities
from services.invoice_service import _classify_ndc
from services.pharmacy_authz import ensure_pharmacy_access

router = APIRouter(tags=["Invoices"])


def _resolve_ndc_fields(item: InvoiceLineItemInput) -> tuple[str | None, str | None, bool]:
    """
    Honor explicit `ndc11`/`upc` if the user typed them in. Otherwise
    fall back to the extractor's `ndc` raw field and classify.
    """
    if item.ndc11 or item.upc:
        return item.ndc11, item.upc, bool(item.verified) if item.verified is not None else True
    return _classify_ndc(item.ndc)


@router.post(
    "/invoices",
    response_model=InvoiceSaveResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Persist an invoice JSON and update inventory (+qty)",
    description=(
        "Accepts the JSON returned by `/documents/process?process_type=invoice` "
        "(optionally with per-line-item `fda_*` / `dm_*` fields spliced in from "
        "a barcode scan). Creates one `Invoice` + N `InvoiceLineItem` rows + "
        "the optional `InvoiceSummary`, then upserts `medicine_inventory` by "
        "`(medical_store_id, code)` adding `invoiced_qty`."
    ),
)
async def save_invoice(
    body: InvoiceSaveRequest,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, body.medical_store_id)

    db_invoice = Invoice(
        medical_store_id=body.medical_store_id,
        document_id=body.document_id,
        source_filename=body.source_filename,
        page_count=body.page_count,
        seller_name=body.seller_name,
        seller_address=body.seller_address,
        seller_phone=body.seller_phone,
        seller_dea=body.seller_dea,
        seller_permit=body.seller_permit,
        seller_fed_id=body.seller_fed_id,
        invoice_number=body.invoice_number,
        invoice_date=body.invoice_date,
        order_number=body.order_number,
        due_date=body.due_date,
        terms_of_payment=body.terms_of_payment,
        your_order_number=body.your_order_number,
        customer_number=body.customer_number,
        customer_name=body.customer_name,
        customer_dea=body.customer_dea,
        customer_state_reg=body.customer_state_reg,
        bill_to_name=body.bill_to_name,
        bill_to_address=body.bill_to_address,
        ship_to_name=body.ship_to_name,
        ship_to_address=body.ship_to_address,
        remit_to_name=body.remit_to_name,
        remit_to_address=body.remit_to_address,
        remit_to_phone=body.remit_to_phone,
        raw_payload=body.model_dump_json(),
    )
    db.add(db_invoice)
    await db.flush()

    for item in body.line_items:
        ndc11, upc, verification_required = _resolve_ndc_fields(item)
        db.add(
            InvoiceLineItem(
                invoice_id=db_invoice.id,
                line=item.line,
                item_code=item.item_code,
                raw_ndc=item.raw_ndc or item.ndc,
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
                fda_package_ndc=item.fda_package_ndc,
                fda_ndc11=item.fda_ndc11,
                dm_gtin=item.dm_gtin,
                dm_serial_number=item.dm_serial_number,
                dm_expiration_date=item.dm_expiration_date,
                dm_lot_number=item.dm_lot_number,
                verified=bool(item.verified) if item.verified is not None else False,
            )
        )

    summary_saved = False
    if body.summary is not None:
        db.add(
            InvoiceSummary(
                invoice_id=db_invoice.id,
                order_line_total=body.summary.order_line_total,
                fuel_surcharge=body.summary.fuel_surcharge,
                sub_total=body.summary.sub_total,
                tax=body.summary.tax,
                grand_total=body.summary.grand_total,
                total_due_by=body.summary.total_due_by,
            )
        )
        summary_saved = True

    await db.flush()

    try:
        inventory_updates_raw = await add_invoice_quantities(
            db,
            medical_store_id=body.medical_store_id,
            invoice_id=db_invoice.id,
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Failed to save invoice: {err}", err=exc)
        raise

    logger.info(
        "Invoice saved: invoice_id={iid} ms_id={ph} lines={n} inv_updates={u}",
        iid=db_invoice.id,
        ph=body.medical_store_id,
        n=len(body.line_items),
        u=len(inventory_updates_raw),
    )

    return InvoiceSaveResponse(
        invoice_id=db_invoice.id,
        medical_store_id=body.medical_store_id,
        line_items_created=len(body.line_items),
        summary_saved=summary_saved,
        inventory_updates=[InventoryUpdate(**u) for u in inventory_updates_raw],
    )
