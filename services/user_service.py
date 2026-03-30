import ast
from fastapi import HTTPException, Request, Response
from core.enums import UserRole
from core.security_schemes import create_access_token, create_refresh_token, verify_refresh_token
from models.pharmacy import Pharmacy
from models.user import User 
from models.refresh_token import RefreshToken
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from argon2 import PasswordHasher
from schemas.login_input_user_schema import Login_Input_User_Schema
from schemas.signup_input_user_schema import Signup_Input_User_Schema
from schemas.signup_input_user_technician_schema import Signup_Input_User_Technician_Schema
from argon2.exceptions import VerifyMismatchError
from schemas.system_internal_user_schema import System_Internal_User_Schema
from schemas.token_data_schemas import TokenData
from schemas.user_update_input import UserUpdateInput
from schemas.user_output import UserOutput
from schemas.message_output import MessageOutput


# ================= HELPERS =================

def _raise_error(status_code: int, message: str):
    """Raise HTTPException with Response_Schema format in detail."""
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None}
    )


def _to_user_output(user_db: User) -> dict:
    """Convert a User DB model to frontend-friendly dict."""
    return UserOutput.model_validate(user_db).model_dump(by_alias=False)


def _get_owner_pharmacy_ids(owner_id: int, db: Session) -> list[int]:
    """Get list of pharmacy IDs owned by a given user."""
    return [
        p.pharmacy_id for p in db.query(Pharmacy).filter(
            Pharmacy.user_id == owner_id
        ).all()
    ]


# ================= AUTH (unchanged) =================

def create_user(user: Signup_Input_User_Schema, db: Session):
    ph = PasswordHasher()
    user_model: User = User(
        username=user.user_name,
        email=user.user_email,
        contact_number=user.contact,
        password_hash=ph.hash(user.input_password)
    )
    try:
        db.add(user_model)
        db.commit()
        db.refresh(user_model)
    except SQLAlchemyError as e:
        db.rollback()
        print("Database error:", str(e))
        _raise_error(500, "Database insert failed")
    except Exception as e:
        db.rollback()
        print("Unexpected error:", str(e))
        _raise_error(500, "Something went wrong while creating user")

    return _to_user_output(user_model)


def login_user(user: Login_Input_User_Schema, response: Response, db: Session):
    ph = PasswordHasher()

    try:
        user_from_db: User = db.query(User).filter(
            User.email == user.user_email,
        ).first()

        if not user_from_db:
            _raise_error(400, "Invalid email or password")

        try:
            ph.verify(user_from_db.password_hash, user.input_password)
        except VerifyMismatchError:
            _raise_error(400, "Invalid email or password")

        access_token = create_access_token({
            "username": user_from_db.username,
            "user_id": user_from_db.user_id
        })
        refresh_token = create_refresh_token({
            "username": user_from_db.username,
            "user_id": user_from_db.user_id
        })

        refresh_token_for_db: RefreshToken = RefreshToken(
            token=ph.hash(refresh_token),
            user=user_from_db
        )
        db.add(refresh_token_for_db)
        db.commit()
        db.refresh(refresh_token_for_db)

        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=False,
            samesite="lax"
        )

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        print("Database error:", str(e))
        _raise_error(500, "Login failed due to database error")
    except Exception as e:
        db.rollback()
        print("Unexpected error:", str(e))
        _raise_error(500, "Something went wrong during login")

    return {"access_token": access_token}


def get_user_by_id(id: str, db):
    try:
        user_from_db: User = db.query(User).filter(
            User.user_id == id,
        ).first()

        if not user_from_db:
            _raise_error(404, "User not found")

        return System_Internal_User_Schema(
            user_id=user_from_db.user_id,
            username=user_from_db.username,
            role=user_from_db.role
        )
    except HTTPException:
        raise
    except Exception as e:
        print("Unexpected error:", str(e))
        _raise_error(500, "Failed to retrieve user")


def generate_new_access_token(req: Request, db: Session):
    try:
        refresh_token = req.cookies.get("refresh_token")
        if not refresh_token:
            _raise_error(401, "No refresh token found")

        data = verify_refresh_token(refresh_token)
        if not data:
            _raise_error(401, "Invalid or expired refresh token")

        token_obj = TokenData(**data)
        user_from_db: User = db.query(User).filter(
            User.user_id == token_obj.owner_id
        ).first()

        if not user_from_db:
            _raise_error(401, "User not found for this token")

        access_token = create_access_token({
            "username": user_from_db.username,
            "user_id": user_from_db.user_id
        })
        return {"access_token": access_token}
    except HTTPException:
        raise
    except Exception as e:
        _raise_error(401, f"Token renewal failed: {str(e)}")


# ================= CREATE TECHNICIAN (STRICT OWNERSHIP) =================

def create_technician(
    technician: Signup_Input_User_Technician_Schema,
    db: Session,
    user: System_Internal_User_Schema
):
    """
    Create a technician.
    - ADMIN: can create for any pharmacy
    - OWNER: can ONLY create for pharmacies they own
    - TECHNICIAN: cannot create
    """
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot create other technicians")

    # STRICT CHECK: Owner must own the pharmacy
    if user.role == UserRole.PHARMACY_OWNER:
        pharmacy = db.query(Pharmacy).filter(
            Pharmacy.pharmacy_id == technician.pharmacy_id
        ).first()

        if not pharmacy:
            _raise_error(404, "Pharmacy not found")

        if pharmacy.user_id != user.user_id:
            _raise_error(403, "You can only create technicians for your own pharmacy")

    ph = PasswordHasher()
    user_model: User = User(
        username=technician.user_name,
        email=technician.user_email,
        contact_number=technician.contact,
        password_hash=ph.hash(technician.input_password),
        role=UserRole.TECHNICIAN
    )

    try:
        pharmacy = db.query(Pharmacy).filter(
            Pharmacy.pharmacy_id == technician.pharmacy_id
        ).first()

        if not pharmacy:
            _raise_error(404, "Pharmacy not found")

        user_model.pharmacies_works = pharmacy
        db.add(user_model)
        db.commit()
        db.refresh(user_model)

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        print("Database error:", str(e))
        _raise_error(500, "Failed to create technician")
    except Exception as e:
        db.rollback()
        print("Unexpected error:", str(e))
        _raise_error(500, "Something went wrong while creating technician")

    return _to_user_output(user_model)


# ================= GET TECHNICIANS (STRICT OWNERSHIP) =================

def get_technician_by_pharmacy_id(
    db: Session,
    user: System_Internal_User_Schema,
    ph_id: int = None
):
    """
    Get technicians.
    - ADMIN: all technicians, optionally filtered by pharmacy
    - OWNER: only technicians of their own pharmacies
    - TECHNICIAN: not allowed
    """
    if user.role == UserRole.TECHNICIAN:
        _raise_error(403, "Technicians cannot access this resource")

    try:
        query = db.query(User).filter(User.role == UserRole.TECHNICIAN)

        if user.role == UserRole.ADMIN:
            if ph_id:
                query = query.filter(User.pharmacy_id == ph_id)
            result = query.all()

        elif user.role == UserRole.PHARMACY_OWNER:
            owner_pharmacy_ids = _get_owner_pharmacy_ids(user.user_id, db)

            if ph_id:
                if ph_id not in owner_pharmacy_ids:
                    _raise_error(403, "You do not own this pharmacy")
                query = query.filter(User.pharmacy_id == ph_id)
            else:
                query = query.filter(User.pharmacy_id.in_(owner_pharmacy_ids))

            result = query.all()
        else:
            _raise_error(403, "Not authorized")
            return

        return [_to_user_output(u) for u in result]

    except HTTPException:
        raise
    except Exception as e:
        print("Unexpected error:", str(e))
        _raise_error(500, "Failed to retrieve technicians")


# ================= UPDATE USER (STRICT OWNERSHIP) =================

def update_user(
    user_id: int,
    update_data: UserUpdateInput,
    db: Session,
    current_user: System_Internal_User_Schema
):
    """
    Update a user by ID.
    - ADMIN: can update anyone
    - OWNER: can update self + technicians of own pharmacies
    - TECHNICIAN: NOT allowed via this route (use /update/me)
    """
    try:
        user_from_db: User = db.query(User).filter(User.user_id == user_id).first()

        if not user_from_db:
            _raise_error(404, "User not found")

        # ADMIN: can update anyone
        if current_user.role == UserRole.ADMIN:
            pass

        # OWNER: can update self or technicians of own pharmacies
        elif current_user.role == UserRole.PHARMACY_OWNER:
            if current_user.user_id == user_id:
                pass  # Updating self
            elif user_from_db.role == UserRole.TECHNICIAN:
                owner_pharmacy_ids = _get_owner_pharmacy_ids(current_user.user_id, db)
                if user_from_db.pharmacy_id not in owner_pharmacy_ids:
                    _raise_error(403, "This technician does not belong to your pharmacy")
            else:
                _raise_error(403, "You can only update yourself or your own technicians")

        else:
            _raise_error(403, "Use /user/update/me to update your own profile")

        # Apply only provided fields (frontend names → DB names)
        update_fields = update_data.model_dump(exclude_unset=True)
        if "name" in update_fields:
            user_from_db.username = update_fields["name"]
        if "user_email" in update_fields:
            user_from_db.email = update_fields["user_email"]
        if "phone" in update_fields:
            user_from_db.contact_number = update_fields["phone"]

        db.commit()
        db.refresh(user_from_db)

        return _to_user_output(user_from_db)

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        print("Database error:", str(e))
        _raise_error(500, "Failed to update user")
    except Exception as e:
        db.rollback()
        print("Unexpected error:", str(e))
        _raise_error(500, "Something went wrong while updating user")


# ================= DELETE USER (STRICT OWNERSHIP) =================

def delete_user(
    user_id: int,
    db: Session,
    current_user: System_Internal_User_Schema
):
    """
    Delete a user by ID.
    - ADMIN: can delete anyone
    - OWNER: can delete self + technicians of own pharmacies
    - TECHNICIAN: NOT allowed via this route (use /delete/me)
    """
    try:
        user_from_db: User = db.query(User).filter(User.user_id == user_id).first()

        if not user_from_db:
            _raise_error(404, "User not found")

        # ADMIN: can delete anyone
        if current_user.role == UserRole.ADMIN:
            pass

        # OWNER: can delete self or technicians of own pharmacies
        elif current_user.role == UserRole.PHARMACY_OWNER:
            if current_user.user_id == user_id:
                pass  # Deleting self
            elif user_from_db.role == UserRole.TECHNICIAN:
                owner_pharmacy_ids = _get_owner_pharmacy_ids(current_user.user_id, db)
                if user_from_db.pharmacy_id not in owner_pharmacy_ids:
                    _raise_error(403, "This technician does not belong to your pharmacy")
            else:
                _raise_error(403, "You can only delete yourself or your own technicians")

        else:
            _raise_error(403, "Use /user/delete/me to delete your own account")

        db.delete(user_from_db)
        db.commit()

        return None

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        print("Database error:", str(e))
        _raise_error(500, "Failed to delete user")
    except Exception as e:
        db.rollback()
        print("Unexpected error:", str(e))
        _raise_error(500, "Something went wrong while deleting user")


# ================= UPDATE SELF (/me) =================

def update_self(
    update_data: UserUpdateInput,
    db: Session,
    current_user: System_Internal_User_Schema
):
    """Update the currently authenticated user's own profile."""
    try:
        user_from_db: User = db.query(User).filter(
            User.user_id == current_user.user_id
        ).first()

        if not user_from_db:
            _raise_error(404, "User not found")

        update_fields = update_data.model_dump(exclude_unset=True)
        if "name" in update_fields:
            user_from_db.username = update_fields["name"]
        if "user_email" in update_fields:
            user_from_db.email = update_fields["user_email"]
        if "phone" in update_fields:
            user_from_db.contact_number = update_fields["phone"]

        db.commit()
        db.refresh(user_from_db)

        return _to_user_output(user_from_db)

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        print("Database error:", str(e))
        _raise_error(500, "Failed to update profile")
    except Exception as e:
        db.rollback()
        print("Unexpected error:", str(e))
        _raise_error(500, "Something went wrong while updating profile")


# ================= DELETE SELF (/me) =================

def delete_self(
    db: Session,
    current_user: System_Internal_User_Schema
):
    """Delete the currently authenticated user's own account."""
    try:
        user_from_db: User = db.query(User).filter(
            User.user_id == current_user.user_id
        ).first()

        if not user_from_db:
            _raise_error(404, "User not found")

        db.delete(user_from_db)
        db.commit()

        return None

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        print("Database error:", str(e))
        _raise_error(500, "Failed to delete account")
    except Exception as e:
        db.rollback()
        print("Unexpected error:", str(e))
        _raise_error(500, "Something went wrong while deleting account")


# ================= GET ALL USERS (Admin Only) =================

def get_all_users(db: Session):
    """Return all users. Admin only (enforced at route level)."""
    try:
        users = db.query(User).all()
        return [_to_user_output(u) for u in users]
    except SQLAlchemyError as e:
        print("Database error:", str(e))
        _raise_error(500, "Failed to retrieve users")


# ================= GET USER BY EMAIL (Admin Only) =================

def get_user_by_email(email: str, db: Session):
    """Find user by email. Admin only (enforced at route level)."""
    try:
        user_from_db: User = db.query(User).filter(User.email == email).first()

        if not user_from_db:
            _raise_error(404, f"No user found with email: {email}")

        return _to_user_output(user_from_db)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        print("Database error:", str(e))
        _raise_error(500, "Failed to search user by email")


# ================= GET USERS BY ROLE (Admin Only) =================

def get_users_by_role(role: str, db: Session):
    """Filter users by role. Admin only (enforced at route level)."""
    try:
        users = db.query(User).filter(User.role == role).all()
        return [_to_user_output(u) for u in users]
    except SQLAlchemyError as e:
        print("Database error:", str(e))
        _raise_error(500, "Failed to retrieve users by role")


# ================= GET CURRENT USER PROFILE =================

def get_current_user_profile(user_id: int, db: Session):
    """Return full profile of the requesting user."""
    try:
        user_from_db: User = db.query(User).filter(User.user_id == user_id).first()

        if not user_from_db:
            _raise_error(404, "User not found")

        return _to_user_output(user_from_db)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        print("Database error:", str(e))
        _raise_error(500, "Failed to retrieve profile")
