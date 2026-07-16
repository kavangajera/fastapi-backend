"""
routes/inventory.py
───────────────────
`GET   /pharmacy/{ph_id}/inventory`         — current stock (search + paging + EXP)
`GET   /pharmacy/{ph_id}/inventory/{code}`  — single-item detail (manufacturer, form, lot, status)
`PATCH /pharmacy/{ph_id}/inventory/{code}`  — manual correction (owner/admin)

EXP dates are only present on rows whose stock was added from a scanned
barcode/QR (`InvoiceLineItem.dm_expiration_date`); otherwise the field is null.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import Feature, UserRole
from middlewares.auth import auth_incoming_req
from schemas.inventory import (
    InventoryAdjustRequest,
    InventoryDetail,
    InventoryListResponse,
    InventoryRow,
)
from schemas.response_schema import Response_Schema, success_response
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.activity_service import log_activity
from services.record_id_service import stamp_on_update
from services.inventory_service import (
    _to_decimal,
    adjust_inventory,
    derive_stock_status,
    get_inventory_detail,
    search_inventory,
)
from services.feature_gate import ensure_feature
from services.pharmacy_authz import ensure_pharmacy_access

router = APIRouter(tags=["Inventory"])


def _to_row(r) -> InventoryRow:
    return InventoryRow(
        code=r.code,
        product_name=r.product_name,
        quantity=str(r.quantity),
        status=derive_stock_status(r.quantity),
        location=r.location,
        exp_date=r.exp_date,
        last_invoice_id=r.last_invoice_id,
        updated_at=r.updated_at,
        record_Identifier=r.record_Identifier,
        update_record_Identifier=r.update_record_Identifier,
        IsDeleted=r.IsDeleted,
        delete_date_at=r.delete_date_at,
        created_at=r.created_at,
        global_time_at=r.global_time_at,
    )


@router.get(
    "/pharmacy/{ph_id}/inventory",
    response_model=Response_Schema,
    summary="Current medicine inventory (search, paging, EXP dates)",
)
async def list_inventory(
    ph_id: int = Path(..., description="medical_store_id"),
    q: str | None = Query(None, description="Search code or product name"),
    only_negative: bool = Query(False, description="Only rows with negative stock"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, ph_id)
    await ensure_feature(db, ph_id, Feature.INVENTORY_LITE)
    rows, total = await search_inventory(
        db, medical_store_id=ph_id, q=q, only_negative=only_negative, skip=skip, limit=limit
    )
    return success_response(
        InventoryListResponse(
            medical_store_id=ph_id,
            items=[_to_row(r) for r in rows],
            total=total,
            skip=skip,
            limit=limit,
        ),
        "Inventory retrieved successfully",
    )


@router.patch(
    "/pharmacy/{ph_id}/inventory/{code}",
    response_model=Response_Schema,
    summary="Manually correct an inventory row (owner/admin) without adding stock",
    description=(
        "Edit product name, quantity (absolute correction — not a delta), and/or "
        "EXP date of an existing inventory row. Records an INVENTORY_ADJUSTED "
        "activity with the before/after diff."
    ),
)
async def update_inventory(
    ph_id: int = Path(..., description="medical_store_id"),
    code: str = Path(..., description="Inventory code (NDC11 or UPC)"),
    body: InventoryAdjustRequest = ...,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, ph_id)
    await ensure_feature(db, ph_id, Feature.INVENTORY_LITE)
    if user.role not in (UserRole.PHARMACY_OWNER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"status_code": 403, "message": "Only owners can adjust inventory", "data": None},
        )

    quantity = _to_decimal(body.quantity) if body.quantity is not None else None
    if body.quantity is not None and quantity is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"status_code": 422, "message": f"Invalid quantity '{body.quantity}'", "data": None},
        )

    row, diff = await adjust_inventory(
        db,
        medical_store_id=ph_id,
        code=code,
        product_name=body.product_name,
        quantity=quantity,
        exp_date=body.exp_date,
        location=body.location,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status_code": 404, "message": f"No inventory row for code '{code}'", "data": None},
        )

    await stamp_on_update(db, row, body.device_id)

    if diff:
        await log_activity(
            db,
            medical_store_id=ph_id,
            actor=user,
            action="INVENTORY_ADJUSTED",
            entity_type="inventory",
            entity_id=row.id,
            summary=f"Adjusted inventory for {code} ({row.product_name or '—'})",
            search_blob=f"{code} {row.product_name or ''}",
            meta={"code": code, "changes": diff},
        )
    await db.commit()
    await db.refresh(row)
    return success_response(_to_row(row), "Inventory updated successfully")


@router.get(
    "/pharmacy/{ph_id}/inventory/{code}",
    response_model=Response_Schema,
    summary="Inventory item detail (manufacturer, dose form, lot, stock status)",
    description=(
        "Single inventory item enriched for the mobile detail view: manufacturer "
        "and dose form from the FDA NDC cache, latest lot number from invoices, "
        "expiry, total stock, and derived stock status."
    ),
)
async def inventory_detail(
    ph_id: int = Path(..., description="medical_store_id"),
    code: str = Path(..., description="Inventory code (NDC11 or UPC)"),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, ph_id)
    await ensure_feature(db, ph_id, Feature.INVENTORY_LITE)
    detail = await get_inventory_detail(db, medical_store_id=ph_id, code=code)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status_code": 404, "message": f"No inventory row for code '{code}'", "data": None},
        )
    r = detail["row"]
    return success_response(
        InventoryDetail(
            code=r.code,
            product_name=r.product_name,
            manufacturer=detail["manufacturer"],
            dosage_form=detail["dosage_form"],
            lot_number=detail["lot_number"],
            exp_date=r.exp_date,
            quantity=str(r.quantity),
            status=derive_stock_status(r.quantity),
            location=r.location,
            last_added=r.updated_at,
            record_Identifier=r.record_Identifier,
            update_record_Identifier=r.update_record_Identifier,
            IsDeleted=r.IsDeleted,
            delete_date_at=r.delete_date_at,
            created_at=r.created_at,
            updated_at=r.updated_at,
            global_time_at=r.global_time_at,
        ),
        "Inventory item retrieved successfully",
    )
