"""
routes/invoice.py
─────────────────
Read-only invoice endpoints. Uploads go through `POST /documents/process`
or the batch endpoint at `POST /pharmacy/{ph_id}/reconciliation` —
they're the only routes that create invoices.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import Feature, ProcessType, UserRole
from middlewares.auth import auth_incoming_req
from models import Invoice, InvoiceLineItem, InvoiceSummary
from models.pharmacy import Pharmacy
from schemas.invoice import InvoiceResponse, InvoiceResponseWrapped
from schemas.pending_document import PendingDocumentItem
from schemas.response_schema import Response_Schema, success_response
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.feature_gate import ensure_feature, entitled_store_ids
from services.inventory_service import reverse_invoice_quantities
from services.pending_documents import document_pending_state, fetch_pending_documents
from services.pharmacy_authz import ensure_pharmacy_access

router = APIRouter(prefix="/invoices", tags=["Invoices"])


async def _accessible_medical_store_ids(
    db: AsyncSession, user: System_Internal_User_Schema
) -> list[int] | None:
    """Return the pharmacy IDs `user` can see, or None for ADMIN (no filter)."""
    if user.role == UserRole.ADMIN:
        return None
    if user.role == UserRole.PHARMACY_OWNER:
        result = await db.execute(
            select(Pharmacy.medical_store_id).where(Pharmacy.user_id == user.user_id)
        )
        return [row[0] for row in result.all()]
    # TECHNICIAN
    return [user.medical_store_id] if user.medical_store_id else []


@router.get("/", response_model=Response_Schema, summary="List invoices")
async def list_invoices(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    stmt = select(Invoice).order_by(Invoice.id.desc()).offset(skip).limit(limit)
    ph_ids = await _accessible_medical_store_ids(db, user)
    if ph_ids is not None:
        # Only show invoices for stores entitled to invoice automation.
        ph_ids = await entitled_store_ids(db, ph_ids, Feature.INVOICE_TO_INVENTORY_AUTO)
        stmt = stmt.where(Invoice.medical_store_id.in_(ph_ids))
    result = await db.execute(stmt)
    invoices = [InvoiceResponseWrapped.model_validate(i) for i in result.scalars().all()]

    pending_items: list[PendingDocumentItem] = []
    if skip == 0 and ph_ids is not None:
        pending_docs = await fetch_pending_documents(
            db,
            process_type=ProcessType.INVOICE.value,
            medical_store_ids=ph_ids,
            saved_model=Invoice,
        )
        pending_items = [
            PendingDocumentItem(
                doc_key=d.doc_key,
                state=document_pending_state(d.status),
                original_filename=d.original_filename,
                error_message=d.error_message,
                created_at=d.created_at,
                updated_at=d.updated_at,
            )
            for d in pending_docs
        ]

    return success_response([*pending_items, *invoices], "Invoices retrieved successfully")


@router.get(
    "/{invoice_id:int}",
    response_model=Response_Schema,
    summary="Get invoice by ID",
)
async def get_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice {invoice_id} not found.",
        )
    await ensure_pharmacy_access(db, user, invoice.medical_store_id)
    await ensure_feature(db, invoice.medical_store_id, Feature.INVOICE_TO_INVENTORY_AUTO)
    return success_response(
        InvoiceResponse.model_validate(invoice), "Invoice retrieved successfully"
    )


@router.delete(
    "/{invoice_id:int}",
    response_model=Response_Schema,
    summary="Delete an invoice and take its stock back out of inventory",
    description=(
        "Soft-deletes the invoice, its line items and its summary, then "
        "reverses the inventory it added (−invoiced_qty per line). Quantities "
        "may go negative, exactly as they can on the dispense side, because "
        "the goods may already have been dispensed."
    ),
)
async def delete_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    # Locked for the transaction: two concurrent deletes of the same invoice
    # would otherwise each reverse its inventory, removing the stock twice.
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id).with_for_update()
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice {invoice_id} not found.",
        )
    await ensure_pharmacy_access(db, user, invoice.medical_store_id)
    await ensure_feature(db, invoice.medical_store_id, Feature.INVOICE_TO_INVENTORY_AUTO)

    # Reverse first — the reversal reads line items through the ORM, which
    # filters soft-deleted rows out, so flagging them first would silently
    # leave the inventory untouched.
    inventory_updates = await reverse_invoice_quantities(
        db, medical_store_id=invoice.medical_store_id, invoice_id=invoice_id
    )

    line_items = (
        await db.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice_id))
    ).scalars().all()
    for item in line_items:
        item.IsDeleted = True

    summary = (
        await db.execute(select(InvoiceSummary).where(InvoiceSummary.invoice_id == invoice_id))
    ).scalar_one_or_none()
    if summary is not None:
        summary.IsDeleted = True

    invoice.IsDeleted = True
    await db.commit()

    logger.info(
        "Invoice deleted: invoice_id={i} ms_id={ph} line_items={n} inventory_touched={t}",
        i=invoice_id,
        ph=invoice.medical_store_id,
        n=len(line_items),
        t=len(inventory_updates),
    )
    return success_response(
        {
            "invoice_id": invoice_id,
            "line_items_removed": len(line_items),
            "summary_removed": summary is not None,
            "inventory_updates": inventory_updates,
        },
        "Invoice deleted and inventory adjusted",
    )
