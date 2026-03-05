from fastapi import Depends, HTTPException
from services import pharmacy
from core.enums import UserRole
from database import get_db
from middlewares.auth import auth_incoming_req
from schemas.pharmacy_input_schema import Pharmacy_Input_Schema
from schemas.system_internal_pharmacy_owner_schema import System_Internal_Pharmacy_Owner_Schema


async def create_pharmacy(input_for_pharmacy:Pharmacy_Input_Schema,db=Depends(get_db),user:System_Internal_Pharmacy_Owner_Schema=Depends(auth_incoming_req)):
    if (user.role!=UserRole.PHARMACY_OWNER):
        raise HTTPException(status_code=403, detail="You can't create Pharmacy")
    
    try:
        return await pharmacy.create_pharmacy(input_for_pharmacy,db)

    except Exception as e:
        raise HTTPException(status_code=500 , detail=e)