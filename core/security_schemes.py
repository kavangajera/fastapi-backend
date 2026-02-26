from datetime import datetime,timedelta, timezone
from fastapi import HTTPException
from jose import ExpiredSignatureError, jwt,JWTError
from schemas.system_internal_pharmacy_owner_schema import System_Internal_Pharmacy_Owner_Schema
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.config import Settings
security = HTTPBearer()


def create_access_token(data:dict):
    to_encode=data.copy()
    time_expire = datetime.now(timezone.utc) + timedelta(minutes=Settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"expire":int(time_expire.timestamp())})
    return jwt.encode(to_encode,Settings.SECRET_KEY,algorithm=Settings.ALGORITHM)

def create_refresh_token(data:dict):
    to_encode=data.copy()
    time_expire = datetime.now(timezone.utc) + timedelta(days=Settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"expire":int(time_expire.timestamp())})
    return jwt.encode(to_encode,Settings.SECRET_KEY,algorithm=Settings.ALGORITHM)

def verify_access_token(token:str):
    
    try:
        data=jwt.decode(token,Settings.SECRET_KEY,Settings.ALGORITHM)
        return data
    except ExpiredSignatureError:
        print("❌ Token has expired")
    except Exception as e:
        raise HTTPException(e)
    