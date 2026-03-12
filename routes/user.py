from fastapi import Depends, HTTPException, Request, Response
from database import get_db
from schemas.login_input_user_schema import Login_Input_User_Schema
from schemas.signup_input_user_schema import Signup_Input_User_Schema
from schemas.signup_output_user_schema import Signup_Output_User_Schema 
from services import user_service
from middlewares import auth
from schemas.response_schema import Response_Schema 

async def create_pharmacy_owner(user:Signup_Input_User_Schema,db=Depends(get_db)):
    
   try:
        
      res:Signup_Output_User_Schema=await user_service.create_User(user,db)
      return Response_Schema(
         statusCode=200,
         data=res
      )
      
   except Exception as e:
      print("Unexpected error:", str(e))
      return Response_Schema(
         statusCode=500,
         data="Something went wrong Server Error"
      )

async def login_pharmacy_owner(user:Login_Input_User_Schema,response:Response,db=Depends(get_db)):
         
   try:
      res:Signup_Output_User_Schema=await user_service.login_User(user,response,db)
      return Response_Schema(
         statusCode=200,
         data=res
      )
      
   except Exception as e:
      print("Unexpected error:", str(e))
      return Response_Schema(
         statusCode=500,
         data="Something went wrong Server Error"
      )

async def renew_access_token(req:Request,db=Depends(get_db)):
   try:
      return Response_Schema(
            statusCode=200,
            data=user_service.generate_new_access_token(req,db)
      )
   except Exception as e:
      print("Unexpected error:", str(e))
      return Response_Schema(
         statusCode=500,
         data="Something went wrong Server Error"
      )