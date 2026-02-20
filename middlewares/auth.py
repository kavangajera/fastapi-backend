from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from core.security_schemes import verify_access_token
from core.database import get_db
from schemas.system_internal_pharmacy_owner_schema import System_Internal_Pharmacy_Owner_Schema
from services.pharmacy_owner import get_pharmacy_owner_by_id

app = FastAPI()

@app.middleware("http")
async def auth_incoming_req(req:Request,call_next,db=Depends(get_db)):

    if req.url.path == "/signup/owner" | req.url.path == "/login/owner" :
        return await call_next(req)
    
    if "authorization" not in req.headers:
        return JSONResponse(content={"message": "Token not found"}, status_code=401)
    
    try:
        data = verify_access_token(req.headers.get("authorization"))
        user:System_Internal_Pharmacy_Owner_Schema=await get_pharmacy_owner_by_id(data.owner_id)
        req.state.user = System_Internal_Pharmacy_Owner_Schema(**user)
        res=await call_next(req)
        return res
    except Exception as e:
        raise HTTPException(e)