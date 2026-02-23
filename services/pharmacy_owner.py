from fastapi import Depends, HTTPException, Response
from core.security_schemes import create_access_token, create_refresh_token
from models.pharmacy_owner import Pharmacy_Owner 
from sqlalchemy.orm import Session
from database import get_db
from sqlalchemy.exc import SQLAlchemyError
from argon2 import PasswordHasher
from schemas.login_input_pharmacy_owner_schema import Login_Input_Pharmacy_Owner_Schema
from schemas.signup_input_phrmacy_owner_schema import Signup_Input_Pharmacy_Owner_Schema
from schemas.signup_output_pharmacy_owner_schema import Signup_Output_Pharmacy_Owner_Schema 
from argon2.exceptions import VerifyMismatchError
from schemas.system_internal_pharmacy_owner_schema import System_Internal_Pharmacy_Owner_Schema



async def create_pharmacy_owner(user:Signup_Input_Pharmacy_Owner_Schema,db:Session):
    ph = PasswordHasher()
    user_model:Pharmacy_Owner = Pharmacy_Owner(
           username=user.username,
           email=user.email,
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
       raise HTTPException(status_code=500, detail="Database insert failed")
   
    except Exception as e:
       db.rollback()
       print("Unexpected error:", str(e))
       raise HTTPException(status_code=500, detail="Something went wrong")
   
   
    return Signup_Output_Pharmacy_Owner_Schema(
            owner_id=user_model.owner_id,
            username=user_model.username,
            email=user_model.email,
            contact=user_model.contact_number
        )           

async def login_pharmacy_owner(user:Login_Input_Pharmacy_Owner_Schema,response:Response,db:Session):

    ph=PasswordHasher()

    try:
        user_from_db:Pharmacy_Owner=db.query(Pharmacy_Owner).filter(
            Pharmacy_Owner.email==user.email,
        ).first()

        try:
            ph.verify(user_from_db.password_hash, user.input_password)
            print("Password is correct!")
        except VerifyMismatchError:
            print("Password is incorrect.")
    
        if not user_from_db:
            raise HTTPException(status_code=400, detail="Invalid credentials")
    
    except SQLAlchemyError as e:
       db.rollback()            # VERY IMPORTANT
       print("Database error:", str(e))
       raise HTTPException(status_code=500, detail="Database insert failed")
   
    except Exception as e:
       db.rollback()
       print("Unexpected error:", str(e))
       raise HTTPException(status_code=500, detail="Something went wrong")
    
    access_token=create_access_token(
        {
            "username":user_from_db.username,
            "owner_id":user_from_db.owner_id
         })
    refresh_token=create_refresh_token( {
            "username":user_from_db.username,
            "owner_id":user_from_db.owner_id
         })

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,          # True in production (HTTPS)
        samesite="lax"
    )

    print("🍪 Refresh token stored in cookie")

    return {"access_token": access_token}

def get_pharmacy_owner_by_id(id:str,db):
    
    try:
        user_from_db:Pharmacy_Owner=db.query(Pharmacy_Owner).filter(
            Pharmacy_Owner.owner_id==id,
        ).first()

        return System_Internal_Pharmacy_Owner_Schema(
            owner_id=user_from_db.owner_id,
            # email=user_from_db.email,
            username=user_from_db.username,
            # contact_number=user_from_db.contact_number,
            role=user_from_db.role
        )
    
    except SQLAlchemyError as e:
       db.rollback()            # VERY IMPORTANT
       print("Database error:", str(e))
       raise HTTPException(status_code=500, detail="Database insert failed")
   
    except Exception as e:
       db.rollback()
       print("Unexpected error:", str(e))
       raise HTTPException(status_code=500, detail="Something went wrong")