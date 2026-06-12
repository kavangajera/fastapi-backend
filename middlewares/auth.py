"""
middlewares/auth.py
───────────────────
Bearer-token gate used as a dependency on protected routes.

    user: System_Internal_User_Schema = Depends(auth_incoming_req)

It is NOT a Starlette middleware — applying it as `Depends(...)` per
route lets FastAPI surface the security scheme in OpenAPI / Swagger and
keeps unauthenticated routes (signup/login) free of the dependency.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from core import security_schemes
from core.async_db import get_async_db
from core.security_schemes import verify_access_token
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.user_service import get_user_by_id


async def auth_incoming_req(
    db: AsyncSession = Depends(get_async_db),
    credentials: HTTPAuthorizationCredentials = Depends(security_schemes.security),
) -> System_Internal_User_Schema:
    try:
        data = verify_access_token(credentials.credentials)
        return await get_user_by_id(data["user_id"], db)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
