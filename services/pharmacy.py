from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from core import enums
from models.pharmacy import Pharmacy
from models.address import Address
from models.user import User, UserRole
from schemas.pharmacy_input_schema import Pharmacy_Input_Schema
from schemas.pharmacy_update_input import PharmacyUpdateInput
from schemas.system_internal_user_schema import System_Internal_User_Schema
from schemas.pharmacy_output import PharmacyOutput
from schemas.message_output import MessageOutput


# ================= HELPERS =================

def _raise_error(status_code: int, message: str):
    """Raise HTTPException with Response_Schema format in detail."""
    raise HTTPException(
        status_code=status_code,
        detail={"status_code": status_code, "message": message, "data": None}
    )


def _to_pharmacy_output(pharmacy_db: Pharmacy) -> dict:
    """Convert a Pharmacy DB model to frontend-friendly dict."""
    return PharmacyOutput.model_validate(pharmacy_db).model_dump(by_alias=False)


def _get_owner_pharmacy_ids(owner_id: int, db: Session) -> list[int]:
    """Get list of pharmacy IDs owned by a given user."""
    return [
        p.pharmacy_id for p in db.query(Pharmacy).filter(
            Pharmacy.user_id == owner_id
        ).all()
    ]


# ================= CREATE PHARMACY =================

def create_pharmacy(
    input_for_pharmacy: Pharmacy_Input_Schema,
    db: Session,
    user: System_Internal_User_Schema
):
    """
    Create pharmacy.
    - ADMIN: can create (assigned to self)
    - OWNER: can create (assigned to self)
    - TECHNICIAN: not allowed (checked at route level)
    """
    try:
        owner_from_db = db.query(User).filter(
            User.user_id == user.user_id
        ).first()

        if not owner_from_db:
            _raise_error(404, "Owner user not found")

        # --- Build Address row (all-nulls if no address provided) ---
        addr_data = {}
        if input_for_pharmacy.address:
            addr_data = input_for_pharmacy.address.model_dump(exclude_unset=True)

        new_address = Address(
            address_line_1=addr_data.get("address_line_1"),
            address_line_2=addr_data.get("address_line_2"),
            city=addr_data.get("city"),
            state=addr_data.get("state"),
            zip_code=addr_data.get("zip_code"),
        )
        db.add(new_address)
        db.flush()  # get the address_id before creating pharmacy

        new_pharmacy: Pharmacy = Pharmacy(
            name=input_for_pharmacy.pharmacy_title,
            code=input_for_pharmacy.pharmacy_code,
            address_id=new_address.address_id,
            owner=owner_from_db
        )

        db.add(new_pharmacy)
        db.commit()
        db.refresh(new_pharmacy)

        return _to_pharmacy_output(new_pharmacy)

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        print("Database error:", str(e))
        _raise_error(500, "Failed to create pharmacy")
    except Exception as e:
        db.rollback()
        print("Unexpected error:", str(e))
        _raise_error(500, "Something went wrong while creating pharmacy")


# ================= GET PHARMACY =================

def get_pharmacy(
    db: Session,
    user: System_Internal_User_Schema,
    ph_id: int = None
):
    """
    Get pharmacies.
    - ADMIN: all pharmacies (with owner info), optionally filtered by ID
    - OWNER: only their own pharmacies, owner info excluded
    - TECHNICIAN: not allowed (checked at route level)
    """
    try:
        if user.role == UserRole.ADMIN:
            query = db.query(Pharmacy)
            if ph_id is not None:
                query = query.filter_by(pharmacy_id=ph_id)
            result = query.all()
            return [_to_pharmacy_output(i) for i in result]

        if user.role == UserRole.PHARMACY_OWNER:
            query = db.query(Pharmacy).filter_by(user_id=user.user_id)
            if ph_id is not None:
                query = query.filter_by(pharmacy_id=ph_id)
            result = query.all()
            output = [_to_pharmacy_output(i) for i in result]
            for s in output:
                s["owner"] = None
            return output

    except HTTPException:
        raise
    except Exception as e:
        print("Unexpected error:", str(e))
        _raise_error(500, "Failed to retrieve pharmacies")


# ================= GET PHARMACY BY OWNER ID (Admin Only) =================

def get_pharmacy_by_owner_id(
    owner_id: int,
    db: Session,
    user: System_Internal_User_Schema
):
    """Get pharmacies by owner user ID. Admin only (checked at route level)."""
    try:
        query = db.query(Pharmacy)
        if owner_id is not None:
            query = query.filter_by(user_id=owner_id)
        result = query.all()
        return [_to_pharmacy_output(i) for i in result]

    except Exception as e:
        print("Unexpected error:", str(e))
        _raise_error(500, "Failed to retrieve pharmacies by owner")


# ================= UPDATE PHARMACY (STRICT OWNERSHIP) =================

def update_pharmacy(
    ph_id: int,
    update_data: PharmacyUpdateInput,
    db: Session,
    user: System_Internal_User_Schema
):
    """
    Update pharmacy fields.
    - ADMIN: can update any pharmacy
    - OWNER: can update ONLY their own pharmacies
    - TECHNICIAN: not allowed (checked at route level)
    """
    try:
        pharmacy: Pharmacy = db.query(Pharmacy).filter(
            Pharmacy.pharmacy_id == ph_id
        ).first()

        if not pharmacy:
            _raise_error(404, "Pharmacy not found")

        # STRICT OWNERSHIP CHECK for non-admin
        if user.role != UserRole.ADMIN:
            if pharmacy.user_id != user.user_id:
                _raise_error(403, "You can only update your own pharmacy")

        # Apply only provided fields
        update_fields = update_data.model_dump(exclude_unset=True)

        if "pharmacy_title" in update_fields:
            pharmacy.name = update_fields["pharmacy_title"]
        if "pharmacy_code" in update_fields:
            pharmacy.code = update_fields["pharmacy_code"]

        # --- Update linked Address if address data provided ---
        if "address" in update_fields and update_fields["address"] is not None:
            addr_update = update_fields["address"]
            address_obj: Address = db.query(Address).filter(
                Address.address_id == pharmacy.address_id
            ).first()

            if address_obj:
                for field_name in ("address_line_1", "address_line_2", "city", "state", "zip_code"):
                    if field_name in addr_update:
                        setattr(address_obj, field_name, addr_update[field_name])

        db.commit()
        db.refresh(pharmacy)

        return _to_pharmacy_output(pharmacy)

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        print("Database error:", str(e))
        _raise_error(500, "Failed to update pharmacy")
    except Exception as e:
        db.rollback()
        print("Unexpected error:", str(e))
        _raise_error(500, "Something went wrong while updating pharmacy")


# ================= DELETE PHARMACY (STRICT OWNERSHIP) =================

def delete_pharmacy(
    ph_id: int,
    db: Session,
    user: System_Internal_User_Schema
):
    """
    Delete a pharmacy.
    - ADMIN: can delete any pharmacy
    - OWNER: can delete ONLY their own pharmacies
    - TECHNICIAN: not allowed (checked at route level)
    """
    try:
        pharmacy: Pharmacy = db.query(Pharmacy).filter(
            Pharmacy.pharmacy_id == ph_id
        ).first()

        if not pharmacy:
            _raise_error(404, "Pharmacy not found")

        # STRICT OWNERSHIP CHECK for non-admin
        if user.role != UserRole.ADMIN:
            if pharmacy.user_id != user.user_id:
                _raise_error(403, "You can only delete your own pharmacy")

        # Delete the linked address first
        address_obj = db.query(Address).filter(
            Address.address_id == pharmacy.address_id
        ).first()

        db.delete(pharmacy)
        if address_obj:
            db.delete(address_obj)

        db.commit()

        return None

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        print("Database error:", str(e))
        _raise_error(500, "Failed to delete pharmacy")
    except Exception as e:
        db.rollback()
        print("Unexpected error:", str(e))
        _raise_error(500, "Something went wrong while deleting pharmacy")


# ================= SEARCH PHARMACY BY NAME =================

def get_pharmacy_by_name(
    name: str,
    db: Session,
    user: System_Internal_User_Schema
):
    """
    Search pharmacies by name (partial match).
    - ADMIN: sees all matching
    - OWNER: sees only their own matching
    - TECHNICIAN: not allowed (checked at route level)
    """
    try:
        query = db.query(Pharmacy).filter(Pharmacy.name.ilike(f"%{name}%"))

        if user.role == UserRole.PHARMACY_OWNER:
            query = query.filter(Pharmacy.user_id == user.user_id)

        result = query.all()
        return [_to_pharmacy_output(i) for i in result]

    except SQLAlchemyError as e:
        print("Database error:", str(e))
        _raise_error(500, "Failed to search pharmacies")
