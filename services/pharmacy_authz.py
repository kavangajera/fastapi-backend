"""
services/pharmacy_authz.py
──────────────────────────
Ownership / role check used by every endpoint that operates on a
specific medical_store_id.

Rules:
    ADMIN            → allowed everywhere
    PHARMACY_OWNER   → must own the requested pharmacy (Pharmacy.user_id)
    TECHNICIAN       → must be assigned to that pharmacy (User.medical_store_id)

On failure raises HTTPException(403). Returns nothing on success.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import UserRole
from models.pharmacy import Pharmacy
from schemas.system_internal_user_schema import System_Internal_User_Schema


def _forbid(message: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"status_code": 403, "message": message, "data": None},
    )


async def ensure_pharmacy_access(
    db: AsyncSession,
    user: System_Internal_User_Schema,
    medical_store_id: int,
) -> None:
    """Raise 403 if `user` cannot operate on `medical_store_id`."""
    if user.role == UserRole.ADMIN:
        return

    if user.role == UserRole.PHARMACY_OWNER:
        result = await db.execute(
            select(Pharmacy.medical_store_id).where(
                Pharmacy.medical_store_id == medical_store_id,
                Pharmacy.user_id == user.user_id,
            )
        )
        if result.scalar_one_or_none() is None:
            _forbid("You do not own this pharmacy")
        return

    if user.role == UserRole.TECHNICIAN:
        if user.medical_store_id != medical_store_id:
            _forbid("You are not assigned to this pharmacy")
        return

    _forbid("Not authorized for this pharmacy")
