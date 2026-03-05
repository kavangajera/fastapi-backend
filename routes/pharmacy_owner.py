from fastapi import Depends, HTTPException, Request, Response
from database import get_db
from schemas.login_input_pharmacy_owner_schema import Login_Input_Pharmacy_Owner_Schema
from schemas.signup_input_phrmacy_owner_schema import Signup_Input_Pharmacy_Owner_Schema
from schemas.signup_output_pharmacy_owner_schema import Signup_Output_Pharmacy_Owner_Schema 
from services import pharmacy_owner
from middlewares import auth

async def create_pharmacy_owner(user:Signup_Input_Pharmacy_Owner_Schema,db=Depends(get_db)):
    
   try:
        
      res:Signup_Output_Pharmacy_Owner_Schema=await pharmacy_owner.create_pharmacy_owner(user,db)
      return res
      
   except Exception as e:
      print("Unexpected error:", str(e))
      raise HTTPException(status_code=500, detail="Something went wrong")

async def login_pharmacy_owner(user:Login_Input_Pharmacy_Owner_Schema,response:Response,db=Depends(get_db)):
         
   try:
      res:Signup_Output_Pharmacy_Owner_Schema=await pharmacy_owner.login_pharmacy_owner(user,response,db)
      return res
      
   except Exception as e:
      print("Unexpected error:", str(e))
      raise HTTPException(status_code=500, detail="Something went wrong")

async def dummy_protacted_route(user=Depends(auth.auth_incoming_req)):
   return user


async def renew_access_token(req:Request,db=Depends(get_db)):
   return pharmacy_owner.generate_new_access_token(req,db)