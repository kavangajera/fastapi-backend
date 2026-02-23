from datetime import datetime,timedelta, timezone
from fastapi import HTTPException
from jose import ExpiredSignatureError, jwt,JWTError
from schemas.system_internal_pharmacy_owner_schema import System_Internal_Pharmacy_Owner_Schema
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()
SECRET_KEY = "CHANGE_THIS_SUPER_SECRET"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=5
REFRESH_TOKEN_EXPIRE_DAYS=1

def create_access_token(data:dict):
    to_encode=data.copy()
    time_expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"expire":int(time_expire.timestamp())})
    return jwt.encode(to_encode,SECRET_KEY,algorithm=ALGORITHM)

def create_refresh_token(data:dict):
    to_encode=data.copy()
    time_expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"expire":int(time_expire.timestamp())})
    return jwt.encode(to_encode,SECRET_KEY,algorithm=ALGORITHM)

def verify_access_token(token:str):
    
    try:
        data=jwt.decode(token,SECRET_KEY,ALGORITHM)
        return data
    except ExpiredSignatureError:
        print("❌ Token has expired")
    except Exception as e:
        raise HTTPException(e)
    