"""
routes/admin_subscription.py
────────────────────────────
ADMIN-only subscription + plan management.

    GET  /admin/subscriptions              — list/filter all subscriptions
    POST /admin/subscriptions              — assign/override a plan for a store
    PUT  /admin/subscriptions/{id}         — modify plan / status / expiry
    POST /admin/subscriptions/{id}/revoke  — cancel + expire immediately
    POST /admin/plans                      — create a plan
    PUT  /admin/plans/{plan_id}            — edit a plan (incl. features JSON)

All routes are gated by ``require_admin`` (403 for non-admins).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from middlewares.auth import require_admin
from schemas.plan_schemas import PlanCreateRequest, PlanOut, PlanUpdateRequest
from schemas.response_schema import Response_Schema, success_response
from schemas.subscription_schemas import (
    AdminAssignRequest,
    AdminModifyRequest,
    SubscriptionOut,
)
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services import plan_service, subscription_service

router = APIRouter(prefix="/admin", tags=["Admin Subscription"])


# ─────────────────────────── Subscriptions ───────────────────────────


@router.get("/subscriptions", response_model=Response_Schema, summary="List subscriptions")
async def list_subscriptions(
    status_filter: str | None = Query(None, alias="status", description="ACTIVE/EXPIRED/CANCELLED"),
    plan_id: int | None = Query(None),
    medical_store_id: int | None = Query(None),
    db: AsyncSession = Depends(get_async_db),
    admin: System_Internal_User_Schema = Depends(require_admin),
):
    subs = await subscription_service.list_subscriptions(
        db, status_filter=status_filter, plan_id=plan_id, medical_store_id=medical_store_id
    )
    return success_response(
        [SubscriptionOut.model_validate(s).model_dump() for s in subs],
        "Subscriptions retrieved successfully",
    )


@router.post(
    "/subscriptions",
    response_model=Response_Schema,
    summary="Assign/override a subscription for a pharmacy",
)
async def assign_subscription(
    body: AdminAssignRequest,
    db: AsyncSession = Depends(get_async_db),
    admin: System_Internal_User_Schema = Depends(require_admin),
):
    sub = await subscription_service.admin_assign(
        db,
        medical_store_id=body.medical_store_id,
        plan_code=body.plan_code.value,
        current_period_end=body.current_period_end,
        status_value=body.status.value if body.status else None,
        actor_user_id=admin.user_id,
        notes=body.notes,
    )
    return success_response(
        SubscriptionOut.model_validate(sub).model_dump(),
        "Subscription assigned successfully",
        status_code=201,
    )


@router.put(
    "/subscriptions/{subscription_id}",
    response_model=Response_Schema,
    summary="Modify a subscription (plan / status / expiry)",
)
async def modify_subscription(
    subscription_id: int = Path(...),
    body: AdminModifyRequest = ...,
    db: AsyncSession = Depends(get_async_db),
    admin: System_Internal_User_Schema = Depends(require_admin),
):
    sub = await subscription_service.admin_modify(
        db,
        subscription_id=subscription_id,
        plan_code=body.plan_code.value if body.plan_code else None,
        status_value=body.status.value if body.status else None,
        current_period_end=body.current_period_end,
        notes=body.notes,
        actor_user_id=admin.user_id,
    )
    return success_response(
        SubscriptionOut.model_validate(sub).model_dump(),
        "Subscription updated successfully",
    )


@router.post(
    "/subscriptions/{subscription_id}/revoke",
    response_model=Response_Schema,
    summary="Revoke a subscription (cancel + expire now)",
)
async def revoke_subscription(
    subscription_id: int = Path(...),
    db: AsyncSession = Depends(get_async_db),
    admin: System_Internal_User_Schema = Depends(require_admin),
):
    sub = await subscription_service.revoke(
        db, subscription_id=subscription_id, actor_user_id=admin.user_id
    )
    return success_response(
        SubscriptionOut.model_validate(sub).model_dump(),
        "Subscription revoked successfully",
    )


# ─────────────────────────────── Plans ───────────────────────────────


@router.post("/plans", response_model=Response_Schema, summary="Create a plan")
async def create_plan(
    body: PlanCreateRequest,
    db: AsyncSession = Depends(get_async_db),
    admin: System_Internal_User_Schema = Depends(require_admin),
):
    plan = await plan_service.create_plan(
        db, {**body.model_dump(), "code": body.code.value}
    )
    return success_response(
        PlanOut.model_validate(plan).model_dump(),
        "Plan created successfully",
        status_code=201,
    )


@router.put("/plans/{plan_id}", response_model=Response_Schema, summary="Edit a plan")
async def edit_plan(
    plan_id: int = Path(...),
    body: PlanUpdateRequest = ...,
    db: AsyncSession = Depends(get_async_db),
    admin: System_Internal_User_Schema = Depends(require_admin),
):
    plan = await plan_service.update_plan(db, plan_id, body.model_dump(exclude_unset=True))
    return success_response(
        PlanOut.model_validate(plan).model_dump(),
        "Plan updated successfully",
    )
