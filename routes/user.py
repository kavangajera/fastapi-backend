from fastapi import Depends, HTTPException, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import UserRole
from middlewares.auth import auth_incoming_req
from schemas.impersonate_input_schema import Impersonate_Input_Schema
from schemas.login_input_user_schema import Login_Input_User_Schema
from schemas.password_reset_schemas import (
    ForgotPasswordInput,
    ResetPasswordInput,
    VerifyResetOtpInput,
)
from schemas.response_schema import Response_Schema
from schemas.signup_input_user_schema import Signup_Input_User_Schema
from schemas.signup_input_user_technician_schema import (
    Signup_Input_User_Technician_Schema,
)
from schemas.user_update_input import UserUpdateInput
from services import password_reset_service, user_service


def _raise_error(status_code: int, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
    )


def success_response(data, message: str = "Success", status_code: int = 200):
    return Response_Schema(status_code=status_code, message=message, data=data)


# ================= AUTH (no middleware) =================


async def create_user(
    user: Signup_Input_User_Schema,
    db: AsyncSession = Depends(get_async_db),
):
    res = await user_service.create_user(user, db)
    return success_response(res, "User created successfully", 201)


async def login_user(
    user: Login_Input_User_Schema,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
):
    res = await user_service.login_user(user, response, db)
    return success_response(res, "Login successful")


async def app_login_user(
    user: Login_Input_User_Schema,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
):
    res = await user_service.login_user(user, response, db, include_password_hash=True)
    return success_response(res, "Login successful")


async def renew_access_token(
    req: Request,
    db: AsyncSession = Depends(get_async_db),
):
    res = await user_service.generate_new_access_token(req, db)
    return success_response(res, "Token renewed successfully")


async def logout_user(
    db: AsyncSession = Depends(get_async_db),
    user=Depends(auth_incoming_req),
):
    res = await user_service.logout_user(db, user)
    return success_response(res, "Logged out successfully")


# ================= FORGOT / RESET PASSWORD (no middleware) =================


async def forgot_password(
    body: ForgotPasswordInput,
    db: AsyncSession = Depends(get_async_db),
):
    res = await password_reset_service.request_password_reset(body, db)
    return success_response(res, res["message"])


async def verify_reset_otp(
    body: VerifyResetOtpInput,
    db: AsyncSession = Depends(get_async_db),
):
    res = await password_reset_service.verify_password_reset_otp(body, db)
    return success_response(res, "Code verified. You can now set a new password.")


async def reset_password(
    body: ResetPasswordInput,
    db: AsyncSession = Depends(get_async_db),
):
    res = await password_reset_service.reset_password(body, db)
    return success_response(res, res["message"])


# ================= IMPERSONATION (Super Admin) =================


async def impersonate_user(
    body: Impersonate_Input_Schema,
    db: AsyncSession = Depends(get_async_db),
    user=Depends(auth_incoming_req),
):
    if user.role != UserRole.ADMIN:
        _raise_error(403, "Only admins can impersonate other users")
    res = await user_service.impersonate_user(
        body.user_id, db, user, body.medical_store_id
    )
    return success_response(res, "Impersonation token issued")


# ================= TECHNICIANS =================


async def create_technician(
    technician: Signup_Input_User_Technician_Schema,
    db: AsyncSession = Depends(get_async_db),
    user=Depends(auth_incoming_req),
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot create other technicians")
    res = await user_service.create_technician(technician, db, user)
    return success_response(res, "Technician created successfully", 201)


async def get_technicians(
    ph_id: int = Query(
        None,
        description="Optional pharmacy ID filter. Omit for all owned pharmacies.",
        examples=[2],
    ),
    db: AsyncSession = Depends(get_async_db),
    user=Depends(auth_incoming_req),
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot access this resource")
    res = await user_service.get_technician_by_medical_store_id(db=db, user=user, ph_id=ph_id)
    return success_response(res, "Technicians retrieved successfully")


# ================= USER UPDATE / DELETE =================


async def update_user(
    user_id: int = Path(..., description="Target user ID.", examples=[12]),
    body: UserUpdateInput = ...,
    db: AsyncSession = Depends(get_async_db),
    user=Depends(auth_incoming_req),
):
    res = await user_service.update_user(user_id, body, db, user)
    return success_response(res, "User updated successfully")


async def delete_user(
    user_id: int = Path(..., description="Target user ID.", examples=[12]),
    db: AsyncSession = Depends(get_async_db),
    user=Depends(auth_incoming_req),
):
    res = await user_service.delete_user(user_id, db, user)
    return success_response(res, "User deleted successfully")


async def update_me(
    body: UserUpdateInput,
    db: AsyncSession = Depends(get_async_db),
    user=Depends(auth_incoming_req),
):
    res = await user_service.update_self(body, db, user)
    return success_response(res, "Profile updated successfully")


async def delete_me(
    db: AsyncSession = Depends(get_async_db),
    user=Depends(auth_incoming_req),
):
    res = await user_service.delete_self(db, user)
    return success_response(res, "Profile deleted successfully")


# ================= ADMIN LISTS =================


async def get_all_users(
    db: AsyncSession = Depends(get_async_db),
    user=Depends(auth_incoming_req),
):
    if user.role != UserRole.ADMIN:
        _raise_error(403, "Only admins can access this resource")
    res = await user_service.get_all_users(db)
    return success_response(res, "Users retrieved successfully")


async def get_user_by_email(
    user_email: str = Query(
        ..., description="Exact email to search.", examples=["user2@gmail.com"]
    ),
    db: AsyncSession = Depends(get_async_db),
    user=Depends(auth_incoming_req),
):
    if user.role != UserRole.ADMIN:
        _raise_error(403, "Only admins can access this resource")
    res = await user_service.get_user_by_email(user_email, db)
    return success_response(res, "User retrieved successfully")


async def get_users_by_role(
    role: str = Query(..., description="Role: OWNER, TECHNICIAN, ADMIN.", examples=["OWNER"]),
    db: AsyncSession = Depends(get_async_db),
    user=Depends(auth_incoming_req),
):
    if user.role != UserRole.ADMIN:
        _raise_error(403, "Only admins can access this resource")
    res = await user_service.get_users_by_role(role, db)
    return success_response(res, "Users retrieved successfully")


async def get_my_profile(
    db: AsyncSession = Depends(get_async_db),
    user=Depends(auth_incoming_req),
):
    res = await user_service.get_current_user_profile(user.user_id, db)
    return success_response(res, "Profile retrieved successfully")
