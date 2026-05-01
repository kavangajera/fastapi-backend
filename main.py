from fastapi import FastAPI, APIRouter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi import HTTPException
import fastapi_swagger_dark as fsd
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from core.config import settings
from routes import router
from routes.pharmacy_purchase_report import router as report_router
from middlewares import auth
app = FastAPI(
    title="Queue RX API",
    version="1.0.0",
    description="""
Queue RX is a pharmacy queue management backend API.

## Authentication

All protected endpoints require a **Bearer token** supplied via the `Authorization` header:
```
Authorization: Bearer <access_token>
```
Obtain an access token by calling `POST /user/login`. Use `GET /user/renew-access-token` (with a valid `refresh_token` cookie) to get a new access token when it expires.

## Roles

| Role | Description |
|------|-------------|
| **OWNER** | Pharmacy owner. Can manage their own pharmacies and technicians. |
| **TECHNICIAN** | Pharmacy staff. Can view their own profile only. Cannot manage pharmacies or other users. |
| **ADMIN** | Superuser. Has access to all endpoints including admin-only routes. |
""",
    openapi_tags=[
        {
            "name": "Auth",
            "description": "Endpoints for user registration, login, and access token renewal.",
        },
        {
            "name": "User",
            "description": "Endpoints for managing user profiles and technician accounts.",
        },
        {
            "name": "Pharmacy",
            "description": "Endpoints for creating, retrieving, updating, and deleting pharmacies.",
        },
        {
            "name": "Ownership Transfer",
            "description": "Endpoints for transferring pharmacy ownership with OTP verification.",
        },
        {
            "name": "Admin",
            "description": "Endpoints restricted to users with the ADMIN role for platform-wide management.",
        },
    ],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    errors = exc.errors()
    error_messages = []
    for error in errors:
        field = ".".join([str(loc) for loc in error.get("loc", []) if loc != "body"])
        msg = error.get("msg", "")
        error_messages.append(f"{field}: {msg}")
    
    combined_message = " | ".join(error_messages) if error_messages else "Validation Error"
    
    return JSONResponse(
        status_code=200,
        content={
            "status_code": 422,
            "message": f"Validation Error: {combined_message}",
            "data": None
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "status_code" in exc.detail:
        return JSONResponse(status_code=200, content=exc.detail)
    
    return JSONResponse(
        status_code=200,
        content={
            "status_code": exc.status_code,
            "message": str(exc.detail),
            "data": None
        }
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(report_router)
@app.get("/")
async def welcome():
    return {"message": "Welcome to Queue RX!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)
