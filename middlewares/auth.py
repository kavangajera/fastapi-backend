from fastapi import Depends, FastAPI, HTTPException, Request
from core import security_schemes
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from core.security_schemes import verify_access_token
from database import get_db
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.user_service import get_user_by_id
from fastapi import Depends, HTTPException


def auth_incoming_req(req:Request,db=Depends(get_db),credentials: HTTPAuthorizationCredentials = Depends(security_schemes.security))->System_Internal_User_Schema:

    token = credentials.credentials
    
    try:
        data = verify_access_token(token)
        return get_user_by_id(data["user_id"],db) 
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))