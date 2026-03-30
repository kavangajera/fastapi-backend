from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from core.enums import UserRole
from database import get_db

from schemas.login_input_user_schema import Login_Input_User_Schema
from schemas.signup_input_user_schema import Signup_Input_User_Schema
from schemas.signup_input_user_technician_schema import Signup_Input_User_Technician_Schema
from schemas.response_schema import Response_Schema
from schemas.user_update_input import UserUpdateInput

from services import user_service
from middlewares.auth import auth_incoming_req


# ================= HELPERS =================

def _raise_error(status_code: int, message: str):
    """Raise HTTPException with Response_Schema format in detail."""
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None}
    )


def success_response(data, message="Success", status_code=200):
    return Response_Schema(status_code=status_code, message=message, data=data)


# ================= AUTH ROUTES (no auth middleware) =================

def create_user(
    user: Signup_Input_User_Schema,
    db: Session = Depends(get_db)
):
    res = user_service.create_user(user, db)
    return success_response(res, "User created successfully", 201)


def login_user(
    user: Login_Input_User_Schema,
    response: Response,
    db: Session = Depends(get_db)
):
    res = user_service.login_user(user, response, db)
    return success_response(res, "Login successful")


def renew_access_token(
    req: Request,
    db: Session = Depends(get_db)
):
    res = user_service.generate_new_access_token(req, db)
    return success_response(res, "Token renewed successfully")


# ================= CREATE TECHNICIAN =================

def create_technician(
    technician: Signup_Input_User_Technician_Schema,
    db: Session = Depends(get_db),
    user=Depends(auth_incoming_req)
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot create other technicians")

    res = user_service.create_technician(technician, db, user)
    return success_response(res, "Technician created successfully", 201)


# ================= GET TECHNICIANS =================

def get_technicians(
    ph_id: int = None,
    db: Session = Depends(get_db),
    user=Depends(auth_incoming_req)
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot access this resource")

    res = user_service.get_technician_by_pharmacy_id(db=db, user=user, ph_id=ph_id)
    return success_response(res, "Technicians retrieved successfully")


# ================= UPDATE USER BY ID =================

def update_user(
    user_id: int,
    body: UserUpdateInput,
    db: Session = Depends(get_db),
    user=Depends(auth_incoming_req)
):
    res = user_service.update_user(user_id, body, db, user)
    return success_response(res, "User updated successfully")


# ================= DELETE USER BY ID =================

def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    user=Depends(auth_incoming_req)
):
    res = user_service.delete_user(user_id, db, user)
    return success_response(res, "User deleted successfully")


# ================= UPDATE SELF (/me) =================

def update_me(
    body: UserUpdateInput,
    db: Session = Depends(get_db),
    user=Depends(auth_incoming_req)
):
    res = user_service.update_self(body, db, user)
    return success_response(res, "Profile updated successfully")


# ================= DELETE SELF (/me) =================

def delete_me(
    db: Session = Depends(get_db),
    user=Depends(auth_incoming_req)
):
    res = user_service.delete_self(db, user)
    return success_response(res, "Profile deleted successfully")


# ================= GET ALL USERS (Admin Only) =================

def get_all_users(
    db: Session = Depends(get_db),
    user=Depends(auth_incoming_req)
):
    if user.role != UserRole.ADMIN:
        _raise_error(403, "Only admins can access this resource")

    res = user_service.get_all_users(db)
    return success_response(res, "Users retrieved successfully")


# ================= GET USER BY EMAIL (Admin Only) =================

def get_user_by_email(
    user_email: str,
    db: Session = Depends(get_db),
    user=Depends(auth_incoming_req)
):
    if user.role != UserRole.ADMIN:
        _raise_error(403, "Only admins can access this resource")

    res = user_service.get_user_by_email(user_email, db)
    return success_response(res, "User retrieved successfully")


# ================= GET USERS BY ROLE (Admin Only) =================

def get_users_by_role(
    role: str,
    db: Session = Depends(get_db),
    user=Depends(auth_incoming_req)
):
    if user.role != UserRole.ADMIN:
        _raise_error(403, "Only admins can access this resource")

    res = user_service.get_users_by_role(role, db)
    return success_response(res, "Users retrieved successfully")


# ================= GET MY PROFILE =================

def get_my_profile(
    db: Session = Depends(get_db),
    user=Depends(auth_incoming_req)
):
    res = user_service.get_current_user_profile(user.user_id, db)
    return success_response(res, "Profile retrieved successfully")
