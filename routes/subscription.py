"""
routes/subscription.py
──────────────────────
Owner/self-serve subscription endpoints:

    GET /plans                          — list purchasable plans (any role)
    GET /subscription/{medical_store_id}— a pharmacy's current subscription
    POST /subscription/subscribe        — start/(re)activate a plan for a store
    PUT  /subscription/upgrade          — change a store's plan mid-cycle

State-only for now (no payment gateway): subscribe/upgrade just set DB state +
expiry. Admin override/revoke lives in ``routes/admin_subscription.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import UserRole
from middlewares.auth import auth_incoming_req
from schemas.payment_schemas import CheckoutSessionResponse, PaymentListResponse, PaymentOut
from schemas.plan_schemas import PlanOut
from schemas.response_schema import Response_Schema, success_response
from schemas.subscription_schemas import (
    CancelRequest,
    SubscribeRequest,
    SubscriptionOut,
    UpgradeRequest,
)
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services import plan_service, subscription_service
from services.pharmacy_authz import ensure_pharmacy_access

router = APIRouter(tags=["Subscription"])


def _require_manage_role(user: System_Internal_User_Schema) -> None:
    """Only owners (of the store) and admins may change a subscription."""
    if user.role not in (UserRole.PHARMACY_OWNER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "status_code": 403,
                "message": "Only pharmacy owners or admins can manage subscriptions",
                "data": None,
            },
        )


@router.get("/plans", response_model=Response_Schema, summary="List available subscription plans")
async def list_plans(
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    plans = await plan_service.list_plans(db, active_only=True)
    return success_response(
        [PlanOut.model_validate(p).model_dump() for p in plans],
        "Plans retrieved successfully",
    )


@router.get(
    "/subscription/{medical_store_id}",
    response_model=Response_Schema,
    summary="Get a pharmacy's current subscription",
)
async def get_subscription(
    medical_store_id: int = Path(..., description="medical_store_id"),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, medical_store_id)
    sub = await subscription_service.get_for_store(db, medical_store_id)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "status_code": 404,
                "message": "This pharmacy has no subscription",
                "data": None,
            },
        )
    return success_response(
        SubscriptionOut.model_validate(sub).model_dump(),
        "Subscription retrieved successfully",
    )


@router.post(
    "/subscription/subscribe",
    response_model=Response_Schema,
    summary="Subscribe a pharmacy to a plan (redirects to Stripe)",
)
async def subscribe(
    body: SubscribeRequest,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, body.medical_store_id)
    _require_manage_role(user)
    checkout_url = await subscription_service.subscribe(
        db,
        medical_store_id=body.medical_store_id,
        plan_code=body.plan_code.value,
        actor_user_id=user.user_id,
    )
    return success_response(
        CheckoutSessionResponse(checkout_url=checkout_url, session_id="").model_dump(),
        "Checkout session created",
        status_code=201,
    )


@router.put(
    "/subscription/upgrade",
    response_model=Response_Schema,
    summary="Change (upgrade/downgrade) a pharmacy's plan",
)
async def upgrade(
    body: UpgradeRequest,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, body.medical_store_id)
    _require_manage_role(user)
    sub = await subscription_service.upgrade(
        db,
        medical_store_id=body.medical_store_id,
        plan_code=body.plan_code.value,
        actor_user_id=user.user_id,
    )
    return success_response(
        SubscriptionOut.model_validate(sub).model_dump(),
        "Plan changed successfully",
    )


@router.post(
    "/subscription/cancel",
    response_model=Response_Schema,
    summary="Cancel a pharmacy's subscription",
)
async def cancel(
    body: CancelRequest,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    await ensure_pharmacy_access(db, user, body.medical_store_id)
    _require_manage_role(user)
    sub = await subscription_service.cancel(
        db,
        medical_store_id=body.medical_store_id,
        actor_user_id=user.user_id,
        immediately=body.cancel_immediately,
    )
    return success_response(
        SubscriptionOut.model_validate(sub).model_dump(),
        "Subscription cancelled successfully",
    )


@router.get(
    "/subscription/{medical_store_id}/payments",
    response_model=Response_Schema,
    summary="List payment history for a pharmacy's subscription",
)
async def list_payments(
    medical_store_id: int = Path(..., description="medical_store_id"),
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    from sqlalchemy import func, select

    from models.payment import SubscriptionPayment
    
    await ensure_pharmacy_access(db, user, medical_store_id)
    
    count_stmt = select(func.count(SubscriptionPayment.payment_id)).where(
        SubscriptionPayment.medical_store_id == medical_store_id
    )
    total = (await db.execute(count_stmt)).scalar() or 0
    
    stmt = (
        select(SubscriptionPayment)
        .where(SubscriptionPayment.medical_store_id == medical_store_id)
        .order_by(SubscriptionPayment.paid_at.desc(), SubscriptionPayment.payment_id.desc())
        .offset(skip)
        .limit(limit)
    )
    payments = (await db.execute(stmt)).scalars().all()
    
    return success_response(
        PaymentListResponse(
            payments=[PaymentOut.model_validate(p) for p in payments],
            total=total
        ).model_dump(),
        "Payment history retrieved successfully",
    )
