"""
routes/inventory.py
───────────────────
`GET /pharmacy/{ph_id}/inventory` — current stock per (medical_store_id, code).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from middlewares.auth import auth_incoming_req
from schemas.inventory import InventoryListResponse, InventoryRow
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.inventory_service import get_inventory
from services.pharmacy_authz import ensure_pharmacy_access

router = APIRouter(tags=["Inventory"])


@router.get(
    "/pharmacy/{ph_id}/inventory",
    response_model=InventoryListResponse,
    summary="Current medicine inventory for a medical store",
)
async def list_inventory(
    ph_id: int = Path(..., description="medical_store_id"),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, ph_id)
    rows = await get_inventory(db, medical_store_id=ph_id)
    items = [
        InventoryRow(
            code=r.code,
            product_name=r.product_name,
            quantity=str(r.quantity),
            last_invoice_id=r.last_invoice_id,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    return InventoryListResponse(medical_store_id=ph_id, items=items, total=len(items))
