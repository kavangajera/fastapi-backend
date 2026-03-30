from fastapi import FastAPI, APIRouter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi import HTTPException
import fastapi_swagger_dark as fsd
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from core.config import settings
from routes import router
from middlewares import auth
app = FastAPI()

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
    allow_origins=[
        settings.FRONTEND_URL
    ],
    allow_credentials=True,  # ⚠️ REQUIRED for cookies!
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
@app.get("/")
async def welcome():
    return {"message": "Welcome to Queue RX!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)