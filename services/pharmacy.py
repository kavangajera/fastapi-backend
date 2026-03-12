from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.pharmacy import Pharmacy
from models.user import User
from schemas.pharmacy_input_schema import Pharmacy_Input_Schema
from schemas.system_internal_user_schema import System_Internal_User_Schema

async def create_pharmacy(input_for_pharmacy:Pharmacy_Input_Schema,db:Session,user:System_Internal_User_Schema):
    try:
        print(user)
        owner_from_db=db.query(User).filter(
            User.user_id==user.user_id
        ).first()
        print(owner_from_db)
        new_pharmacy:Pharmacy=Pharmacy(
            name=input_for_pharmacy.name,
            address=input_for_pharmacy.address,
            owner=owner_from_db
        )
        print(new_pharmacy)

        db.add(new_pharmacy)
        db.commit()
        db.refresh(new_pharmacy)

        return new_pharmacy

    except Exception as e:
        raise HTTPException(status_code=500, detail="DataBase error")
