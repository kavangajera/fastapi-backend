from fastapi import HTTPException
from sqlalchemy.orm import Session
from core import enums
from models.pharmacy import Pharmacy
from models.user import User, UserRole
from schemas.pharmacy_input_schema import Pharmacy_Input_Schema
from schemas.system_internal_user_schema import System_Internal_User_Schema
from schemas.pharmacy_get_output_schema import PharmacyGetOutputSchema

def create_pharmacy(input_for_pharmacy:Pharmacy_Input_Schema,db:Session,user:System_Internal_User_Schema):
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

        return PharmacyGetOutputSchema.model_validate(new_pharmacy).model_dump(by_alias=False)

    except Exception as e:
        raise HTTPException(status_code=500, detail="DataBase error")

# Get All Pharmacy
# 1)For Admin
# 2)For Owner

# Get phrmacy by pharmacy id
# 1)For Admin include Pharmacy Owner Name and Mail
# 2)For Owner just details

# Get pharmacy by owner
# 1)Only for Admin

#If Id provided then filter otherwise return all pharmacy
# this service used by Getall and GetByPhramacyID
def get_pharmacy(db:Session,user:System_Internal_User_Schema,ph_id:int=None):

# Return Everything
    try:
        if(user.role==UserRole.ADMIN):
        
            query = db.query(Pharmacy)
            if ph_id is not None:
                query = query.filter_by(pharmacy_id=ph_id)
            result = query.all()
            schemas = [PharmacyGetOutputSchema.model_validate(i).model_dump(by_alias=False) for i in result]
            return schemas
    
# Not returning Owner of Pharmacy In case of Query by owner it self
# Also return pharmacy owned by Owner only not All

        if(user.role==UserRole.PHARMACY_OWNER):
            query = db.query(Pharmacy).filter_by(user_id=user.user_id)
            if ph_id is not None:
                query = query.filter_by(pharmacy_id=ph_id)

            result = query.all()
            schemas = [PharmacyGetOutputSchema.model_validate(i).model_dump(by_alias=False) for i in result]
            for s in schemas:
                s.PharmacyOwner = None
            return schemas
        
    except Exception as e:
        raise HTTPException(status_code=500, detail={"DataBase error",e})
        
def get_pharmacy_by_owner_id(owner_id:int,db:Session,user:System_Internal_User_Schema):

    try:
        if(user.role==UserRole.ADMIN):
        
            query = db.query(Pharmacy)
            if owner_id is not None:
                query = query.filter_by(user_id=owner_id)
            result = query.all()
            schemas = [PharmacyGetOutputSchema.model_validate(i).model_dump(by_alias=False) for i in result]
            return schemas


    except Exception as e:
        raise HTTPException(status_code=500, detail={"DataBase error",e})