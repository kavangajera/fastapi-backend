"""
schemas/plan_schemas.py
───────────────────────
Request/response models for the subscription plan catalog.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.enums import PlanCode


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plan_id: int
    code: str
    name: str
    description: str | None = None
    tier: int
    monthly_price_cents: int
    features: list[str] = Field(default_factory=list)
    limits: dict | None = None
    is_active: bool


class PlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: PlanCode
    name: str
    description: str | None = None
    tier: int = 1
    monthly_price_cents: int = 0
    features: list[str] = Field(default_factory=list)
    limits: dict | None = None
    is_active: bool = True


class PlanUpdateRequest(BaseModel):
    """Partial update — only provided fields change. ``code`` is immutable."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    tier: int | None = None
    monthly_price_cents: int | None = None
    features: list[str] | None = None
    limits: dict | None = None
    is_active: bool | None = None
