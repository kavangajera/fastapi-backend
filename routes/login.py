from fastapi import Depends, HTTPException, Response
from schemas.login_input_pharmacy_owner_schema import Login_Input_Pharmacy_Owner_Schema
from models.pharmacy_owner import Pharmacy_Owner 
from core.database import get_db
from sqlalchemy.orm import Session
from core.security_schemes import create_access_token,create_refresh_token

async def login(user:Login_Input_Pharmacy_Owner_Schema,response:Response,db:Session=Depends(get_db)):


    user_from_db:Pharmacy_Owner=db.query(Pharmacy_Owner).filter(
        Pharmacy_Owner.email==user.email,
        Pharmacy_Owner.password_hash==user.input_password
        ).first()
    
    if not user_from_db:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    
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