"""
routes/invoice.py
─────────────────
Read-only invoice endpoints. Uploads go through `POST /documents/process`
or the batch endpoint at `POST /pharmacy/{ph_id}/reconciliation` —
they're the only routes that create invoices.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import UserRole
from middlewares.auth import auth_incoming_req
from models import Invoice
from models.pharmacy import Pharmacy
from schemas.invoice import InvoiceResponse
from schemas.response_schema import Response_Schema, success_response
from schemas.system_internal_user_schema import System_Internal_User_Schema
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
        stmt = stmt.where(Invoice.medical_store_id.in_(ph_ids))
    result = await db.execute(stmt)
    invoices = [InvoiceResponse.model_validate(i) for i in result.scalars().all()]
    return success_response(invoices, "Invoices retrieved successfully")


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
    return success_response(
        InvoiceResponse.model_validate(invoice), "Invoice retrieved successfully"
    )
