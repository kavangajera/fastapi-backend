from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from fastapi.security import HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt

from core.config import settings

security = HTTPBearer()


def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    to_encode = data.copy()
    minutes = expires_minutes if expires_minutes is not None else settings.ACCESS_TOKEN_EXPIRE_MINUTES
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    to_encode.update({"expire": int(expires_at.timestamp())})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"expire": int(expires_at.timestamp())})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has expired",
        ) from exc
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        ) from exc


def verify_refresh_token(refresh_token: str) -> dict:
    try:
        return jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
        ) from exc
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from exc


# ─────────────────────────────────────────────────────────────────────
# Temperature-device session tokens
# ─────────────────────────────────────────────────────────────────────
# These are NOT user tokens: they are minted for a registered logging
# device after it presents its secret, and are deliberately longer-lived
# (settings.TEMPERATURE_DEVICE_TOKEN_EXPIRE_MINUTES) so an unattended
# logger is not re-authenticating constantly.
#
# NB the expiry claim here is the standard `exp`, unlike the `expire`
# claim used by create_access_token above. python-jose only enforces
# `exp`, so this is what actually makes a device token stop working when
# its window elapses — which the re-authenticate-with-the-secret step of
# the logging flow depends on.

DEVICE_TOKEN_SCOPE = "temperature_device"


def create_device_token(
    *,
    temperature_device_id: int,
    medical_store_id: int,
    session_id: int,
    jti: str,
    expires_minutes: int | None = None,
) -> tuple[str, datetime]:
    """Mint a session token for a temperature device.

    Returns ``(token, expires_at)`` where ``expires_at`` is **naive UTC**,
    matching the timestamp convention used by the ORM models.
    """
    minutes = (
        expires_minutes
        if expires_minutes is not None
        else settings.TEMPERATURE_DEVICE_TOKEN_EXPIRE_MINUTES
    )
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=minutes)
    payload = {
        "scope": DEVICE_TOKEN_SCOPE,
        "temperature_device_id": temperature_device_id,
        "medical_store_id": medical_store_id,
        "session_id": session_id,
        # The revocation handle: the session stores the jti it currently
        # honours, so re-issuing (or stopping) invalidates the old token.
        "jti": jti,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, expires_at.replace(tzinfo=None)


def verify_device_token(token: str) -> dict:
    """Decode a device session token, or raise 401.

    Only checks the signature, expiry, and scope — whether the token is still
    the session's *current* one is a DB question, answered in
    ``middlewares/device_auth.py``.
    """
    try:
        data = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status_code": 401,
                "message": "Device token has expired. Re-authenticate with the device secret.",
                "data": {"reason": "TOKEN_EXPIRED"},
            },
        ) from exc
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status_code": 401,
                "message": "Invalid device token",
                "data": {"reason": "TOKEN_INVALID"},
            },
        ) from exc

    if data.get("scope") != DEVICE_TOKEN_SCOPE:
        # A user access token must never work as a device token.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status_code": 401,
                "message": "Not a temperature device token",
                "data": {"reason": "TOKEN_INVALID"},
            },
        )
    return data
