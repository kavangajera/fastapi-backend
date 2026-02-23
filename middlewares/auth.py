from fastapi import Depends, FastAPI, HTTPException, Request
from core import security_schemes
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from core.security_schemes import verify_access_token
from database import get_db
from schemas.system_internal_pharmacy_owner_schema import System_Internal_Pharmacy_Owner_Schema
from services.pharmacy_owner import get_pharmacy_owner_by_id
from fastapi import Depends, HTTPException

app = FastAPI()

def auth_incoming_req(req:Request,db=Depends(get_db),credentials: HTTPAuthorizationCredentials = Depends(security_schemes.security)):

    token = credentials.credentials
    
    try:
        data = verify_access_token(token)
        print(data)
        return get_pharmacy_owner_by_id(data["owner_id"],db) 
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))