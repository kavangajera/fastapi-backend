import ast
from fastapi import HTTPException, Request, Response
from core.security_schemes import create_access_token, create_refresh_token, verify_refresh_token
from models.user import User 
from models.refresh_token import RefreshToken
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from argon2 import PasswordHasher
from schemas.login_input_user_schema import Login_Input_User_Schema
from schemas.signup_input_user_schema import Signup_Input_User_Schema
from schemas.signup_output_user_schema import Signup_Output_User_Schema 
from argon2.exceptions import VerifyMismatchError
from schemas.system_internal_user_schema import System_Internal_User_Schema
from schemas.token_data_schemas import TokenData

def create_User(user:Signup_Input_User_Schema,db:Session):
    ph = PasswordHasher()
    user_model:User = User(
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
   
   
    return Signup_Output_User_Schema(
            user_id=user_model.user_id,
            username=user_model.username,
            email=user_model.email,
            contact=user_model.contact_number
        )           

def login_User(user:Login_Input_User_Schema,response:Response,db:Session):

    ph=PasswordHasher()

    try:
        user_from_db:User=db.query(User).filter(
            User.email==user.email,
        ).first()
        print(user_from_db)
        try:
            ph.verify(user_from_db.password_hash, user.input_password)
            print("Password is correct!")
        except VerifyMismatchError:
            print("Password is incorrect.")
    
        if not user_from_db:
            raise HTTPException(status_code=400, detail="Invalid credentials")
    
    
    
        access_token=create_access_token(
        {
            "username":user_from_db.username,
            "user_id":user_from_db.user_id
         })
        refresh_token=create_refresh_token( {
            "username":user_from_db.username,
            "user_id":user_from_db.user_id
         })
        
        refresh_token_for_db:RefreshToken=RefreshToken(
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
        secure=False,          # True in production (HTTPS)
        samesite="lax"
        )

        print("🍪 Refresh token stored in cookie")
    except SQLAlchemyError as e:
       db.rollback()            # VERY IMPORTANT
       print("Database error:", str(e))
       raise HTTPException(status_code=500, detail="Database insert failed")
   
    except Exception as e:
       db.rollback()
       print("Unexpected error:", str(e))
       raise HTTPException(status_code=500, detail="Something went wrong")

    return {"access_token": access_token}
    

def get_User_by_id(id:str,db):
    
    try:
        user_from_db:User=db.query(User).filter(
            User.user_id==id,
        ).first()

        return System_Internal_User_Schema(
            user_id=user_from_db.user_id,
            username=user_from_db.username,
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

def generate_new_access_token(req:Request,db:Session):
        try:
            refresh_token=req.cookies.get("refresh_token")
            data=verify_refresh_token(refresh_token)
            print(data)
            token_obj = TokenData(**data)
            user_from_db:User=db.query(User).filter(
            User.user_id==token_obj.owner_id
            ).first()
            print(user_from_db)
            access_token=create_access_token(
            {
                "username":user_from_db.username,
                "user_id":user_from_db.owner_id
            })
            print(data)
            return {"access_token": access_token}
        except Exception as e:
            raise HTTPException(status_code=401, detail=str(e))