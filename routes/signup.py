from fastapi import Depends, HTTPException
from schemas.signup_input_phrmacy_owner_schema import Signup_Input_Pharmacy_Owner_Schema
from models.pharmacy_owner import Pharmacy_Owner 
from core.database import get_db
from sqlalchemy.orm import Session
from schemas.signup_output_pharmacy_owner_schema import Signup_Output_Pharmacy_Owner_Schema 
from sqlalchemy.exc import SQLAlchemyError

async def create_user(user:Signup_Input_Pharmacy_Owner_Schema,db:Session=Depends(get_db)):


   try:
       user_model = Pharmacy_Owner(
           username=user.username,
           email=user.email,
           contact_number=user.contact,
           password_hash=user.input_password
       )
   
       db.add(user_model)
       db.commit()
       db.refresh(user_model)   # optional but recommended
   
   except SQLAlchemyError as e:
       db.rollback()            # VERY IMPORTANT
       print("Database error:", str(e))
       raise HTTPException(status_code=500, detail="Database insert failed")
   
   except Exception as e:
       db.rollback()
       print("Unexpected error:", str(e))
       raise HTTPException(status_code=500, detail="Something went wrong")
   
   finally:
        return Signup_Output_Pharmacy_Owner_Schema(
            owner_id=user_model.owner_id,
            username=user_model.username,
            email=user_model.email,
            contact=user_model.contact_number
        )           
