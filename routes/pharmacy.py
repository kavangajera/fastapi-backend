from fastapi import Depends, HTTPException
from schemas.response_schema import Response_Schema
from services import pharmacy
from core.enums import UserRole
from database import get_db
from middlewares.auth import auth_incoming_req
from schemas.pharmacy_input_schema import Pharmacy_Input_Schema
from schemas.system_internal_user_schema import System_Internal_User_Schema
# Admin can change number of pharmacy
def create_pharmacy(input_for_pharmacy:Pharmacy_Input_Schema,db=Depends(get_db),user:System_Internal_User_Schema=Depends(auth_incoming_req)):
    if (user.role==UserRole.TECHNICIAN):
        raise HTTPException(status_code=403, detail="You can't create Pharmacy")
    
    try:
        return Response_Schema(
         statusCode=200,
         data=pharmacy.create_pharmacy(input_for_pharmacy,db,user)
      ) 

    except Exception as e:
        return Response_Schema(
         statusCode=500,
         data={"Something went wrong Server Error",e}
      )

def get_pharmacy(ph_id:int=None,db=Depends(get_db),user:System_Internal_User_Schema=Depends(auth_incoming_req)):

    if(user.role==UserRole.TECHNICIAN):
        raise HTTPException(status_code=403, detail="You can't search Pharmacy")
    try:

        return Response_Schema(
            statusCode=200,
            data=pharmacy.get_pharmacy(db,user,ph_id)
        )

    except Exception as e:
        return Response_Schema(
         statusCode=500,
         data={"Something went wrong Server Error",e}
      )

def get_pharmacy_by_owner_id(owner_id:int,db=Depends(get_db),user:System_Internal_User_Schema=Depends(auth_incoming_req)):

    if(user.role==UserRole.TECHNICIAN):
         return Response_Schema(
         statusCode=500,
         data={"You can't access"}
      )
    
    if(owner_id is None):
        return Response_Schema(
         statusCode=500,
         data={"Must provide owner id"}
      )

    try:

        return Response_Schema(
            statusCode=200,
            data=pharmacy.get_pharmacy_by_owner_id(owner_id,db,user)
        )

    except Exception as e:
        return Response_Schema(
         statusCode=500,
         data={"Something went wrong Server Error",e}
      )




# async def update_pharmacy():


# async def delete_pharmacy():
