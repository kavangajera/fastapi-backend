"""
services/activity_service.py
────────────────────────────
Single entry point for writing `activity_log` rows.

`log_activity` only `db.add(...)`s the row — it never commits. The caller's
existing transaction commits it alongside the domain rows so an event is
recorded iff the action it describes actually persisted.

`actor` is the `System_Internal_User_Schema` that every authenticated route
already has from `Depends(auth_incoming_req)`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from models import ActivityLog
from schemas.system_internal_user_schema import System_Internal_User_Schema


async def log_activity(
    db: AsyncSession,
    *,
    medical_store_id: int,
    actor: System_Internal_User_Schema | None,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    summary: str | None = None,
    customer_name: str | None = None,
    wholesaler_name: str | None = None,
    search_blob: str | None = None,
    error_count: int = 0,
    meta: dict | None = None,
) -> ActivityLog:
    """Add an audit-log row to the current session (no commit)."""
    row = ActivityLog(
        medical_store_id=medical_store_id,
        actor_user_id=actor.user_id if actor else None,
        actor_role=actor.role.value if actor else None,
        actor_name=actor.username if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        customer_name=customer_name,
        wholesaler_name=wholesaler_name,
        search_blob=(search_blob or None),
        error_count=error_count,
        has_errors=error_count > 0,
        meta=meta,
    )
    db.add(row)
    return row


def build_search_blob(*parts: str | None) -> str | None:
    """Join non-empty drug names / NDCs / descriptions for the LIKE filter."""
    tokens = [str(p).strip() for p in parts if p and str(p).strip()]
    return " ".join(tokens) if tokens else None
