from fastapi import Depends, HTTPException
from schemas.response_schema import Response_Schema
from schemas.pharmacy_update_input import PharmacyUpdateInput
from services import pharmacy
from core.enums import UserRole
from database import get_db
from middlewares.auth import auth_incoming_req
from schemas.pharmacy_input_schema import Pharmacy_Input_Schema
from schemas.system_internal_user_schema import System_Internal_User_Schema


# ================= HELPERS =================

def _raise_error(status_code: int, message: str):
    """Raise HTTPException with Response_Schema format in detail."""
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None}
    )


def success_response(data, message="Success", status_code=200):
    return Response_Schema(status_code=status_code, message=message, data=data)


# ================= CREATE PHARMACY =================

def create_pharmacy(
    input_for_pharmacy: Pharmacy_Input_Schema,
    db=Depends(get_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req)
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot create pharmacies")

    res = pharmacy.create_pharmacy(input_for_pharmacy, db, user)
    return success_response(res, "Pharmacy created successfully", 201)


# ================= GET PHARMACY =================

def get_pharmacy(
    ph_id: int = None,
    db=Depends(get_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req)
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot access pharmacy data")

    res = pharmacy.get_pharmacy(db, user, ph_id)
    return success_response(res, "Pharmacy retrieved successfully")


# ================= GET PHARMACY BY OWNER (Admin Only) =================

def get_pharmacy_by_owner_id(
    owner_id: int,
    db=Depends(get_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req)
):
    if user.role != UserRole.ADMIN:
        _raise_error(403, "Only admins can search pharmacies by owner")

    if owner_id is None:
        _raise_error(400, "Must provide owner id")

    res = pharmacy.get_pharmacy_by_owner_id(owner_id, db, user)
    return success_response(res, "Pharmacies retrieved successfully")


# ================= UPDATE PHARMACY =================

def update_pharmacy(
    ph_id: int,
    body: PharmacyUpdateInput,
    db=Depends(get_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req)
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot update pharmacies")

    res = pharmacy.update_pharmacy(ph_id, body, db, user)
    return success_response(res, "Pharmacy updated successfully")


# ================= DELETE PHARMACY =================

def delete_pharmacy(
    ph_id: int,
    db=Depends(get_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req)
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot delete pharmacies")

    res = pharmacy.delete_pharmacy(ph_id, db, user)
    return success_response(res, "Pharmacy deleted successfully")


# ================= SEARCH PHARMACY BY NAME =================

def get_pharmacy_by_name(
    name: str,
    db=Depends(get_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req)
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot search pharmacies")

    res = pharmacy.get_pharmacy_by_name(name, db, user)
    return success_response(res, "Pharmacies retrieved successfully")
