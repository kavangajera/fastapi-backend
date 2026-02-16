from fastapi import Depends
from schemas.phrmacy_owner_schema import Pharmacy_Owner_Schema
from models.pharmacy_owner import Pharmacy_Owner 
from core.database import get_db
from sqlalchemy.orm import Session

async def create_user(user:Pharmacy_Owner_Schema,db:Session=Depends(get_db)):

    user_model=Pharmacy_Owner(owner_id=1,username=user.username,email=user.email,contact_number=user.contact,password_hash=user.input_password)


    db.add(user_model)
    db.commit()
    return user