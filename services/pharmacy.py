from __future__ import annotations

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import UserRole
from models.pharmacy import Pharmacy
from models.user import User
from schemas.pharmacy_input_schema import Pharmacy_Input_Schema
from schemas.pharmacy_output import PharmacyOutput
from schemas.pharmacy_update_input import PharmacyUpdateInput
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.record_id_service import stamp_on_create, stamp_on_update


def _raise_error(status_code: int, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
    )


def _to_pharmacy_output(pharmacy_db: Pharmacy) -> dict:
    return PharmacyOutput.model_validate(pharmacy_db).model_dump(by_alias=False)


# ================= CREATE =================


async def create_pharmacy(
    input_for_pharmacy: Pharmacy_Input_Schema,
    db: AsyncSession,
    user: System_Internal_User_Schema,
):
    owner_result = await db.execute(select(User).where(User.user_id == user.user_id))
    owner_from_db = owner_result.scalar_one_or_none()
    if not owner_from_db:
        _raise_error(404, "Owner user not found")

    new_pharmacy = Pharmacy(
        name=input_for_pharmacy.pharmacy_title,
        address=input_for_pharmacy.pharmacy_location,
        city=input_for_pharmacy.city,
        state=input_for_pharmacy.state,
        zip_code=input_for_pharmacy.zip_code,
        store_code=input_for_pharmacy.store_code,
        user_id=owner_from_db.user_id,
    )
    await stamp_on_create(db, new_pharmacy, input_for_pharmacy.device_id)

    try:
        db.add(new_pharmacy)
        await db.commit()
        await db.refresh(new_pharmacy)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to create pharmacy: {err}", err=str(exc))
        _raise_error(500, "Failed to create pharmacy")

    return _to_pharmacy_output(new_pharmacy)


# ================= GET =================


async def get_pharmacy(
    db: AsyncSession,
    user: System_Internal_User_Schema,
    ph_id: int | None = None,
):
    if user.role == UserRole.ADMIN:
        stmt = select(Pharmacy)
        if ph_id is not None:
            stmt = stmt.where(Pharmacy.medical_store_id == ph_id)
        result = await db.execute(stmt)
        return [_to_pharmacy_output(p) for p in result.scalars().all()]

    if user.role == UserRole.PHARMACY_OWNER:
        stmt = select(Pharmacy).where(Pharmacy.user_id == user.user_id)
        if ph_id is not None:
            stmt = stmt.where(Pharmacy.medical_store_id == ph_id)
        result = await db.execute(stmt)
        output = [_to_pharmacy_output(p) for p in result.scalars().all()]
        for entry in output:
            entry["owner"] = None
        return output

    _raise_error(403, "Not authorized to list pharmacies")


async def get_pharmacy_by_owner_id(
    owner_id: int,
    db: AsyncSession,
    user: System_Internal_User_Schema,
):
    stmt = select(Pharmacy)
    if owner_id is not None:
        stmt = stmt.where(Pharmacy.user_id == owner_id)
    result = await db.execute(stmt)
    return [_to_pharmacy_output(p) for p in result.scalars().all()]


# ================= UPDATE =================


async def update_pharmacy(
    ph_id: int,
    update_data: PharmacyUpdateInput,
    db: AsyncSession,
    user: System_Internal_User_Schema,
):
    result = await db.execute(select(Pharmacy).where(Pharmacy.medical_store_id == ph_id))
    pharmacy = result.scalar_one_or_none()
    if not pharmacy:
        _raise_error(404, "Pharmacy not found")

    if user.role != UserRole.ADMIN and pharmacy.user_id != user.user_id:
        _raise_error(403, "You can only update your own pharmacy")

    update_fields = update_data.model_dump(exclude_unset=True)
    if "pharmacy_title" in update_fields:
        pharmacy.name = update_fields["pharmacy_title"]
    if "pharmacy_location" in update_fields:
        pharmacy.address = update_fields["pharmacy_location"]
    for field in ("city", "state", "zip_code", "store_code"):
        if field in update_fields:
            setattr(pharmacy, field, update_fields[field])

    await stamp_on_update(db, pharmacy, update_data.device_id)

    try:
        await db.commit()
        await db.refresh(pharmacy)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to update pharmacy: {err}", err=str(exc))
        _raise_error(500, "Failed to update pharmacy")

    return _to_pharmacy_output(pharmacy)


# ================= DELETE =================


async def delete_pharmacy(
    ph_id: int,
    db: AsyncSession,
    user: System_Internal_User_Schema,
):
    result = await db.execute(select(Pharmacy).where(Pharmacy.medical_store_id == ph_id))
    pharmacy = result.scalar_one_or_none()
    if not pharmacy:
        _raise_error(404, "Pharmacy not found")

    if user.role != UserRole.ADMIN and pharmacy.user_id != user.user_id:
        _raise_error(403, "You can only delete your own pharmacy")

    try:
        pharmacy.IsDeleted = True
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to delete pharmacy: {err}", err=str(exc))
        _raise_error(500, "Failed to delete pharmacy")

    return {"medical_store_id": ph_id}


# ================= SEARCH BY NAME =================


async def get_pharmacy_by_name(
    name: str,
    db: AsyncSession,
    user: System_Internal_User_Schema,
):
    stmt = select(Pharmacy).where(Pharmacy.name.ilike(f"%{name}%"))
    if user.role == UserRole.PHARMACY_OWNER:
        stmt = stmt.where(Pharmacy.user_id == user.user_id)
    result = await db.execute(stmt)
    return [_to_pharmacy_output(p) for p in result.scalars().all()]
