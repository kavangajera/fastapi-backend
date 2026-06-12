from fastapi import Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import UserRole
from middlewares.auth import auth_incoming_req
from schemas.pharmacy_input_schema import Pharmacy_Input_Schema
from schemas.pharmacy_update_input import PharmacyUpdateInput
from schemas.response_schema import Response_Schema
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services import pharmacy


def _raise_error(status_code: int, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
    )


def success_response(data, message: str = "Success", status_code: int = 200):
    return Response_Schema(status_code=status_code, message=message, data=data)


async def create_pharmacy(
    input_for_pharmacy: Pharmacy_Input_Schema,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot create pharmacies")
    res = await pharmacy.create_pharmacy(input_for_pharmacy, db, user)
    return success_response(res, "Pharmacy created successfully", 201)


async def get_pharmacy(
    ph_id: int = Query(None, description="Optional pharmacy id.", examples=[2]),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot access pharmacy data")
    res = await pharmacy.get_pharmacy(db, user, ph_id)
    return success_response(res, "Pharmacy retrieved successfully")


async def get_pharmacy_by_owner_id(
    owner_id: int = Query(..., description="Owner user id.", examples=[4]),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    if user.role != UserRole.ADMIN:
        _raise_error(403, "Only admins can search pharmacies by owner")
    if owner_id is None:
        _raise_error(400, "Must provide owner id")
    res = await pharmacy.get_pharmacy_by_owner_id(owner_id, db, user)
    return success_response(res, "Pharmacies retrieved successfully")


async def update_pharmacy(
    ph_id: int = Path(..., description="Pharmacy id to update.", examples=[2]),
    body: PharmacyUpdateInput = ...,
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot update pharmacies")
    res = await pharmacy.update_pharmacy(ph_id, body, db, user)
    return success_response(res, "Pharmacy updated successfully")


async def delete_pharmacy(
    ph_id: int = Path(..., description="Pharmacy id to delete.", examples=[2]),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot delete pharmacies")
    res = await pharmacy.delete_pharmacy(ph_id, db, user)
    return success_response(res, "Pharmacy deleted successfully")


async def get_pharmacy_by_name(
    name: str = Query(..., description="Pharmacy name (partial match).", examples=["Deva"]),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot search pharmacies")
    res = await pharmacy.get_pharmacy_by_name(name, db, user)
    return success_response(res, "Pharmacies retrieved successfully")
