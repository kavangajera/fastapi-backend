from datetime import datetime,timedelta, timezone
from fastapi import HTTPException
from jose import ExpiredSignatureError, jwt,JWTError
from schemas.system_internal_pharmacy_owner_schema import System_Internal_Pharmacy_Owner_Schema
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.config import settings
security = HTTPBearer()


def create_access_token(data:dict):
    to_encode=data.copy()
    time_expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"expire":int(time_expire.timestamp())})
    return jwt.encode(to_encode,settings.SECRET_KEY,algorithm=settings.ALGORITHM)

def create_refresh_token(data:dict):
    to_encode=data.copy()
    time_expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"expire":int(time_expire.timestamp())})
    return jwt.encode(to_encode,settings.SECRET_KEY,algorithm=settings.ALGORITHM)

def verify_access_token(token:str):
    
    try:
        data=jwt.decode(token,settings.SECRET_KEY,settings.ALGORITHM)
        return data
    except ExpiredSignatureError:
        print("❌ Token has expired")
    except Exception as e:
        raise HTTPException(e)

def verify_refresh_token(refresh_token:str):
    
    try:
        data=jwt.decode(refresh_token,settings.SECRET_KEY,settings.ALGORITHM)
        return data
    except ExpiredSignatureError:
        print("❌ Refresh Token has expired")
    except Exception as e:
        raise HTTPException(e)
    