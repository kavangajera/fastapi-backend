from datetime import datetime,timedelta, timezone
from jose import jwt,JWTError

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