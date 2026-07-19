"""
schemas/subscription_schemas.py
───────────────────────────────
Request/response models for pharmacy subscriptions.

Request bodies use ``medical_store_id`` (matching the rest of the API's write
contracts); responses expose it as ``pharmacy_id`` via ``validation_alias``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.enums import PlanCode, SubscriptionStatus
from schemas.plan_schemas import PlanOut


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subscription_id: int
    pharmacy_id: int = Field(validation_alias="medical_store_id")
    plan_id: int
    plan: PlanOut | None = None
    status: str
    started_at: datetime
    current_period_end: datetime
    cancelled_at: datetime | None = None
    notes: str | None = None
    stripe_subscription_id: str | None = None


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    medical_store_id: int
    cancel_immediately: bool = False


class SubscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medical_store_id: int
    plan_code: PlanCode


class UpgradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medical_store_id: int
    plan_code: PlanCode


class AdminAssignRequest(BaseModel):
    """Admin override — force any plan/expiry/status onto a store."""

    model_config = ConfigDict(extra="forbid")

    medical_store_id: int
    plan_code: PlanCode
    current_period_end: datetime | None = None
    status: SubscriptionStatus | None = None
    notes: str | None = None


class AdminModifyRequest(BaseModel):
    """Partial admin edit of an existing subscription by id."""

    model_config = ConfigDict(extra="forbid")

    plan_code: PlanCode | None = None
    status: SubscriptionStatus | None = None
    current_period_end: datetime | None = None
    notes: str | None = None
