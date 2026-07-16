"""
services/plan_service.py
────────────────────────
CRUD for the subscription plan catalog (``models.plan.Plan``).

The plan's ``features`` JSON is the entitlement source of truth read by
``services.feature_gate``. Admins manage the catalog via
``routes/admin_subscription.py``; everyone can list active plans.
"""

from __future__ import annotations

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import Feature
from models.plan import Plan


def _raise(status_code: int, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
    )


def _validate_features(features: list[str] | None) -> list[str]:
    """Reject unknown feature keys so a typo can't silently grant/deny access."""
    if not features:
        return []
    valid = {f.value for f in Feature}
    unknown = [f for f in features if f not in valid]
    if unknown:
        _raise(422, f"Unknown feature key(s): {', '.join(unknown)}")
    return list(features)


async def list_plans(db: AsyncSession, active_only: bool = True) -> list[Plan]:
    stmt = select(Plan).order_by(Plan.tier.asc())
    if active_only:
        stmt = stmt.where(Plan.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_plan_by_code(db: AsyncSession, code: str) -> Plan | None:
    result = await db.execute(select(Plan).where(Plan.code == code))
    return result.scalar_one_or_none()


async def get_plan(db: AsyncSession, plan_id: int) -> Plan | None:
    return await db.get(Plan, plan_id)


async def create_plan(db: AsyncSession, data: dict) -> Plan:
    if await get_plan_by_code(db, data["code"]):
        _raise(409, f"A plan with code '{data['code']}' already exists")

    plan = Plan(
        code=data["code"],
        name=data["name"],
        description=data.get("description"),
        tier=data.get("tier", 1),
        monthly_price_cents=data.get("monthly_price_cents", 0),
        features=_validate_features(data.get("features")),
        limits=data.get("limits"),
        is_active=data.get("is_active", True),
    )
    try:
        db.add(plan)
        await db.commit()
        await db.refresh(plan)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to create plan: {err}", err=str(exc))
        _raise(500, "Failed to create plan")
    return plan


async def update_plan(db: AsyncSession, plan_id: int, data: dict) -> Plan:
    plan = await get_plan(db, plan_id)
    if plan is None:
        _raise(404, "Plan not found")

    for field in (
        "name",
        "description",
        "tier",
        "monthly_price_cents",
        "limits",
        "is_active",
    ):
        if field in data:
            setattr(plan, field, data[field])
    if "features" in data:
        plan.features = _validate_features(data["features"])

    try:
        await db.commit()
        await db.refresh(plan)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to update plan: {err}", err=str(exc))
        _raise(500, "Failed to update plan")
    return plan
