from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, Response
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import UserRole
from core.security_schemes import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
)
from models.pharmacy import Pharmacy
from models.refresh_token import RefreshToken
from models.user import User
from schemas.login_input_user_schema import Login_Input_User_Schema
from schemas.signup_input_user_schema import Signup_Input_User_Schema
from schemas.signup_input_user_technician_schema import (
    Signup_Input_User_Technician_Schema,
)
from schemas.system_internal_user_schema import System_Internal_User_Schema
from schemas.token_data_schemas import TokenData
from schemas.user_output import UserOutput
from schemas.user_update_input import UserUpdateInput

# ================= HELPERS =================


def _raise_error(status_code: int, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None},
    )


def _to_user_output(user_db: User) -> dict:
    return UserOutput.model_validate(user_db).model_dump(by_alias=False)


async def _get_owner_medical_store_ids(owner_id: int, db: AsyncSession) -> list[int]:
    result = await db.execute(select(Pharmacy.medical_store_id).where(Pharmacy.user_id == owner_id))
    return [row[0] for row in result.all()]


# ================= AUTH =================


async def create_user(user: Signup_Input_User_Schema, db: AsyncSession):
    ph = PasswordHasher()
    username = user.user_email.split("@")[0]
    user_model = User(
        username=username,
        email=user.user_email,
        contact_number="1234567890",
        password_hash=ph.hash(user.input_password),
    )
    try:
        db.add(user_model)
        await db.commit()
        await db.refresh(user_model)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Database error creating user: {err}", err=str(exc))
        _raise_error(500, "Database insert failed")
    except Exception as exc:
        await db.rollback()
        logger.error("Unexpected error creating user: {err}", err=str(exc))
        _raise_error(500, "Something went wrong while creating user")

    return _to_user_output(user_model)


async def login_user(user: Login_Input_User_Schema, response: Response, db: AsyncSession):
    ph = PasswordHasher()

    try:
        result = await db.execute(select(User).where(User.email == user.user_email))
        user_from_db = result.scalar_one_or_none()

        if not user_from_db:
            _raise_error(400, "Invalid email or password")

        try:
            ph.verify(user_from_db.password_hash, user.input_password)
        except VerifyMismatchError:
            _raise_error(400, "Invalid email or password")

        access_token = create_access_token(
            {"username": user_from_db.username, "user_id": user_from_db.user_id}
        )
        refresh_token = create_refresh_token(
            {"username": user_from_db.username, "user_id": user_from_db.user_id}
        )

        refresh_token_for_db = RefreshToken(
            token=ph.hash(refresh_token), user_id=user_from_db.user_id
        )
        db.add(refresh_token_for_db)
        await db.commit()

        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=False,
            samesite="lax",
        )

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Database error during login: {err}", err=str(exc))
        _raise_error(500, "Login failed due to database error")
    except Exception as exc:
        await db.rollback()
        logger.error("Unexpected error during login: {err}", err=str(exc))
        _raise_error(500, "Something went wrong during login")

    return {
        "access_token": access_token,
        "refresh_token":refresh_token,
        "id": user_from_db.user_id,
        "email": user_from_db.email,
        "role": user_from_db.role.value,
    }


async def get_user_by_id(user_id: int, db: AsyncSession) -> System_Internal_User_Schema:
    result = await db.execute(select(User).where(User.user_id == user_id))
    user_from_db = result.scalar_one_or_none()
    if not user_from_db:
        _raise_error(404, "User not found")
    return System_Internal_User_Schema(
        user_id=user_from_db.user_id,
        username=user_from_db.username,
        role=user_from_db.role,
        medical_store_id=user_from_db.medical_store_id,
    )


async def generate_new_access_token(req: Request, db: AsyncSession):
    refresh_token = req.cookies.get("refresh_token")
    if not refresh_token:
        _raise_error(401, "No refresh token found")

    data = verify_refresh_token(refresh_token)
    if not data:
        _raise_error(401, "Invalid or expired refresh token")

    token_obj = TokenData(**data)
    result = await db.execute(select(User).where(User.user_id == token_obj.owner_id))
    user_from_db = result.scalar_one_or_none()
    if not user_from_db:
        _raise_error(401, "User not found for this token")

    access_token = create_access_token(
        {"username": user_from_db.username, "user_id": user_from_db.user_id}
    )
    return {"access_token": access_token}


# ================= CREATE TECHNICIAN =================


async def create_technician(
    technician: Signup_Input_User_Technician_Schema,
    db: AsyncSession,
    user: System_Internal_User_Schema,
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot create other technicians")

    pharmacy_result = await db.execute(
        select(Pharmacy).where(Pharmacy.medical_store_id == technician.medical_store_id)
    )
    pharmacy = pharmacy_result.scalar_one_or_none()
    if not pharmacy:
        _raise_error(404, "Pharmacy not found")

    if user.role == UserRole.PHARMACY_OWNER and pharmacy.user_id != user.user_id:
        _raise_error(403, "You can only create technicians for your own pharmacy")

    ph = PasswordHasher()
    user_model = User(
        username=technician.user_name,
        email=technician.user_email,
        contact_number=technician.contact,
        password_hash=ph.hash(technician.input_password),
        role=UserRole.TECHNICIAN,
        medical_store_id=pharmacy.medical_store_id,
    )

    try:
        db.add(user_model)
        await db.commit()
        await db.refresh(user_model)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to create technician: {err}", err=str(exc))
        _raise_error(500, "Failed to create technician")

    return _to_user_output(user_model)


# ================= GET TECHNICIANS =================


async def get_technician_by_medical_store_id(
    db: AsyncSession,
    user: System_Internal_User_Schema,
    ph_id: int | None = None,
):
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot access this resource")

    stmt = select(User).where(User.role == UserRole.TECHNICIAN)

    if user.role == UserRole.ADMIN:
        if ph_id:
            stmt = stmt.where(User.medical_store_id == ph_id)
    elif user.role == UserRole.PHARMACY_OWNER:
        owner_medical_store_ids = await _get_owner_medical_store_ids(user.user_id, db)
        if ph_id:
            if ph_id not in owner_medical_store_ids:
                _raise_error(403, "You do not own this pharmacy")
            stmt = stmt.where(User.medical_store_id == ph_id)
        else:
            stmt = stmt.where(User.medical_store_id.in_(owner_medical_store_ids))
    else:
        _raise_error(403, "Not authorized")

    result = await db.execute(stmt)
    technicians = result.scalars().all()
    return [_to_user_output(u) for u in technicians]


# ================= UPDATE USER =================


async def update_user(
    user_id: int,
    update_data: UserUpdateInput,
    db: AsyncSession,
    current_user: System_Internal_User_Schema,
):
    result = await db.execute(select(User).where(User.user_id == user_id))
    user_from_db = result.scalar_one_or_none()
    if not user_from_db:
        _raise_error(404, "User not found")

    if current_user.role == UserRole.ADMIN:
        pass
    elif current_user.role == UserRole.PHARMACY_OWNER:
        if current_user.user_id == user_id:
            pass
        elif user_from_db.role == UserRole.TECHNICIAN:
            owner_medical_store_ids = await _get_owner_medical_store_ids(current_user.user_id, db)
            if user_from_db.medical_store_id not in owner_medical_store_ids:
                _raise_error(403, "This technician does not belong to your pharmacy")
        else:
            _raise_error(403, "You can only update yourself or your own technicians")
    else:
        _raise_error(403, "Use /user/update/me to update your own profile")

    update_fields = update_data.model_dump(exclude_unset=True)
    if "name" in update_fields:
        user_from_db.username = update_fields["name"]
    if "user_email" in update_fields:
        user_from_db.email = update_fields["user_email"]
    if "phone" in update_fields:
        user_from_db.contact_number = update_fields["phone"]

    try:
        await db.commit()
        await db.refresh(user_from_db)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to update user: {err}", err=str(exc))
        _raise_error(500, "Failed to update user")

    return _to_user_output(user_from_db)


# ================= DELETE USER =================


async def delete_user(
    user_id: int,
    db: AsyncSession,
    current_user: System_Internal_User_Schema,
):
    result = await db.execute(select(User).where(User.user_id == user_id))
    user_from_db = result.scalar_one_or_none()
    if not user_from_db:
        _raise_error(404, "User not found")

    if current_user.role == UserRole.ADMIN:
        pass
    elif current_user.role == UserRole.PHARMACY_OWNER:
        if current_user.user_id == user_id:
            pass
        elif user_from_db.role == UserRole.TECHNICIAN:
            owner_medical_store_ids = await _get_owner_medical_store_ids(current_user.user_id, db)
            if user_from_db.medical_store_id not in owner_medical_store_ids:
                _raise_error(403, "This technician does not belong to your pharmacy")
        else:
            _raise_error(403, "You can only delete yourself or your own technicians")
    else:
        _raise_error(403, "Use /user/delete/me to delete your own account")

    try:
        await db.delete(user_from_db)
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to delete user: {err}", err=str(exc))
        _raise_error(500, "Failed to delete user")

    return None


# ================= /me =================


async def update_self(
    update_data: UserUpdateInput,
    db: AsyncSession,
    current_user: System_Internal_User_Schema,
):
    result = await db.execute(select(User).where(User.user_id == current_user.user_id))
    user_from_db = result.scalar_one_or_none()
    if not user_from_db:
        _raise_error(404, "User not found")

    update_fields = update_data.model_dump(exclude_unset=True)
    if "name" in update_fields:
        user_from_db.username = update_fields["name"]
    if "user_email" in update_fields:
        user_from_db.email = update_fields["user_email"]
    if "phone" in update_fields:
        user_from_db.contact_number = update_fields["phone"]

    try:
        await db.commit()
        await db.refresh(user_from_db)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to update profile: {err}", err=str(exc))
        _raise_error(500, "Failed to update profile")

    return _to_user_output(user_from_db)


async def delete_self(
    db: AsyncSession,
    current_user: System_Internal_User_Schema,
):
    result = await db.execute(select(User).where(User.user_id == current_user.user_id))
    user_from_db = result.scalar_one_or_none()
    if not user_from_db:
        _raise_error(404, "User not found")

    try:
        await db.delete(user_from_db)
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to delete account: {err}", err=str(exc))
        _raise_error(500, "Failed to delete account")

    return None


# ================= ADMIN LISTS =================


async def get_all_users(db: AsyncSession):
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [_to_user_output(u) for u in users]


async def get_user_by_email(email: str, db: AsyncSession):
    result = await db.execute(select(User).where(User.email == email))
    user_from_db = result.scalar_one_or_none()
    if not user_from_db:
        _raise_error(404, f"No user found with email: {email}")
    return _to_user_output(user_from_db)


async def get_users_by_role(role: str, db: AsyncSession):
    result = await db.execute(select(User).where(User.role == role))
    users = result.scalars().all()
    return [_to_user_output(u) for u in users]


async def get_current_user_profile(user_id: int, db: AsyncSession):
    result = await db.execute(select(User).where(User.user_id == user_id))
    user_from_db = result.scalar_one_or_none()
    if not user_from_db:
        _raise_error(404, "User not found")
    return _to_user_output(user_from_db)
