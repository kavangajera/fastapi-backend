"""
routes/activity.py
──────────────────
`GET /pharmacy/{ph_id}/activity` — the owner's operational feed.

One row per recorded action (document uploaded, dispense saved / force-saved,
invoice saved, inventory adjusted, refill customer dismissed). Backed entirely
by `activity_log`, whose denormalized `customer_name` / `wholesaler_name` /
`search_blob` columns let every filter run as an indexed `WHERE ... LIKE`
without joining back into the domain tables.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from middlewares.auth import auth_incoming_req
from models import ActivityLog
from schemas.activity import ActivityListResponse, ActivityRow
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.pharmacy_authz import ensure_pharmacy_access

router = APIRouter(tags=["Activity"])


@router.get(
    "/pharmacy/{ph_id}/activity",
    response_model=ActivityListResponse,
    summary="Owner activity feed (uploads, saves, force-saves, purchases, sales, adjustments)",
    description=(
        "Returns recorded actions newest-first. Filter by time range, action, "
        "customer (dispense patient), wholesaler (invoice seller), medicine "
        "(drug name or NDC), acting user, and whether the entry carried errors."
    ),
)
async def list_activity(
    ph_id: int = Path(..., description="medical_store_id"),
    date_from: datetime | None = Query(None, description="created_at >= (ISO 8601)"),
    date_to: datetime | None = Query(None, description="created_at <= (ISO 8601)"),
    action: str | None = Query(None, description="Exact action code, e.g. INVOICE_SAVED"),
    customer: str | None = Query(None, description="Substring match on customer name"),
    wholesaler: str | None = Query(None, description="Substring match on supplier/seller name"),
    medicine: str | None = Query(None, description="Substring match on drug name or NDC"),
    actor_user_id: int | None = Query(None, description="Filter by acting user"),
    has_errors: bool | None = Query(None, description="Only entries with/without errors"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, ph_id)

    filters = [ActivityLog.medical_store_id == ph_id]
    if date_from is not None:
        filters.append(ActivityLog.created_at >= date_from)
    if date_to is not None:
        filters.append(ActivityLog.created_at <= date_to)
    if action:
        filters.append(ActivityLog.action == action)
    if customer:
        filters.append(ActivityLog.customer_name.ilike(f"%{customer}%"))
    if wholesaler:
        filters.append(ActivityLog.wholesaler_name.ilike(f"%{wholesaler}%"))
    if medicine:
        filters.append(ActivityLog.search_blob.ilike(f"%{medicine}%"))
    if actor_user_id is not None:
        filters.append(ActivityLog.actor_user_id == actor_user_id)
    if has_errors is not None:
        filters.append(ActivityLog.has_errors.is_(has_errors))

    total = (
        await db.execute(select(func.count(ActivityLog.id)).where(*filters))
    ).scalar() or 0

    rows = (
        await db.execute(
            select(ActivityLog)
            .where(*filters)
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()

    return ActivityListResponse(
        medical_store_id=ph_id,
        items=[ActivityRow.model_validate(r) for r in rows],
        total=total,
        skip=skip,
        limit=limit,
    )
