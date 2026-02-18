from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

async def auth_incoming_req(req:Request,call_next):

    if req.url.path == "/signup" | req.url.path == "/login" :
        return await call_next(req)
    
    if "authorization" not in req.headers:
        return JSONResponse(content={"message": "Token not found"}, status_code=401)

    if 