"""
schemas/activity.py
───────────────────
Response models for `GET /pharmacy/{ph_id}/activity`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ActivityRow(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    created_at: datetime
    action: str
    actor_user_id: int | None = None
    actor_role: str | None = None
    actor_name: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    summary: str | None = None
    customer_name: str | None = None
    wholesaler_name: str | None = None
    error_count: int = 0
    has_errors: bool = False
    meta: dict[str, Any] | None = None


class ActivityListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medical_store_id: int
    items: list[ActivityRow]
    total: int
    skip: int
    limit: int
