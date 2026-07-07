from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, Response
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import UserRole
from core.record_ids import is_valid_device_id
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
from services.record_id_service import (
    resolve_device,
    stamp_on_create,
    stamp_on_update,
)

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
        await db.flush()  # assign user_id before device association / stamping
        if is_valid_device_id(user.device_id):
            await resolve_device(
                db, device_id=user.device_id, user_id=user_model.user_id
            )
        await stamp_on_create(db, user_model, user.device_id)
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


async def login_user(
    user: Login_Input_User_Schema,
    response: Response,
    db: AsyncSession,
    include_password_hash: bool = False,
):
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
        # On successful login the account is active and no longer logged out.
        user_from_db.IsActive = 1
        user_from_db.IsLogout = 0

        # Register / refresh the calling device and pin its source prefix so
        # every record id generated for it carries the right platform code.
        # Missing / malformed ids are generated server-side; the canonical
        # value is returned below for the client to store.
        device = await resolve_device(
            db,
            device_id=user.device_id,
            source_prefix=user.source,
            platform=user.source_platform,
            user_id=user_from_db.user_id,
        )
        canonical_device_id = device.device_id

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

    data = {
        "access_token": access_token,
        "refresh_token":refresh_token,
        "user_id": user_from_db.user_id,
        "email": user_from_db.email,
        "role": user_from_db.role.value,
        "device_id": canonical_device_id,
        "record_Identifier": user_from_db.record_Identifier,
        "update_record_Identifier": user_from_db.update_record_Identifier,
        "IsDeleted": user_from_db.IsDeleted,
        "delete_date_at": user_from_db.delete_date_at,
        "created_at": user_from_db.created_at,
        "updated_at": user_from_db.updated_at,
        "global_time_at": user_from_db.global_time_at,
        "IsActive": user_from_db.IsActive,
        "IsLogout": user_from_db.IsLogout,
    }
    # /app/login returns the stored Argon2id password hash so the mobile
    # app can verify credentials offline (the hash is self-describing —
    # salt + params are embedded — so no server secret is needed on-device).
    if include_password_hash:
        data["password_hash"] = user_from_db.password_hash
    return data


# Impersonation access tokens are minted by an ADMIN to view the app as another
# user. They are intentionally longer-lived than the default 5-minute access
# token (no refresh cookie is issued cross-domain), but still expire so the
# elevated session cannot live forever.
IMPERSONATION_TOKEN_EXPIRE_MINUTES = 60


async def impersonate_user(
    target_user_id: int,
    db: AsyncSession,
    admin: System_Internal_User_Schema,
    medical_store_id: int | None = None,
):
    if admin.role != UserRole.ADMIN:
        _raise_error(403, "Only admins can impersonate other users")

    result = await db.execute(select(User).where(User.user_id == target_user_id))
    target = result.scalar_one_or_none()
    if not target:
        _raise_error(404, "Target user not found")

    # If a pharmacy was chosen, make sure it actually belongs to the target user
    # (owner) so the admin can't be redirected into a store the user can't access.
    if medical_store_id is not None:
        ph_result = await db.execute(
            select(Pharmacy).where(Pharmacy.medical_store_id == medical_store_id)
        )
        pharmacy = ph_result.scalar_one_or_none()
        if not pharmacy:
            _raise_error(404, "Pharmacy not found")
        if pharmacy.user_id != target.user_id:
            _raise_error(400, "Selected pharmacy does not belong to the target user")

    access_token = create_access_token(
        {"username": target.username, "user_id": target.user_id},
        expires_minutes=IMPERSONATION_TOKEN_EXPIRE_MINUTES,
    )

    return {
        "access_token": access_token,
        "user_id": target.user_id,
        "email": target.email,
        "role": target.role.value,
        "pharmacy_id": medical_store_id,
        "record_Identifier": target.record_Identifier,
        "update_record_Identifier": target.update_record_Identifier,
        "IsDeleted": target.IsDeleted,
        "delete_date_at": target.delete_date_at,
        "created_at": target.created_at,
        "updated_at": target.updated_at,
        "global_time_at": target.global_time_at,
        "IsActive": target.IsActive,
        "IsLogout": target.IsLogout,
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
    result = await db.execute(select(User).where(User.user_id == token_obj.user_id))
    user_from_db = result.scalar_one_or_none()
    if not user_from_db:
        _raise_error(401, "User not found for this token")

    access_token = create_access_token(
        {"username": user_from_db.username, "user_id": user_from_db.user_id}
    )
    return {"access_token": access_token}


# ================= LOGOUT =================


async def logout_user(db: AsyncSession, current_user: System_Internal_User_Schema):
    """Mark the current user as logged out (sets ``IsLogout = 1``)."""
    result = await db.execute(select(User).where(User.user_id == current_user.user_id))
    user_from_db = result.scalar_one_or_none()
    if not user_from_db:
        _raise_error(404, "User not found")

    user_from_db.IsLogout = 1
    try:
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("Failed to log out user: {err}", err=str(exc))
        _raise_error(500, "Failed to log out")

    return None


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
        await db.flush()
        await stamp_on_create(db, user_model, technician.device_id)
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

    await stamp_on_update(db, user_from_db, update_data.device_id)

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
        user_from_db.IsDeleted = True
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

    await stamp_on_update(db, user_from_db, update_data.device_id)

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
        user_from_db.IsDeleted = True
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
