from fastapi import FastAPI, APIRouter
import fastapi_swagger_dark as fsd
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from core.config import settings
from routes import router
from middlewares import auth
app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL
    ],
    allow_credentials=True,  # ⚠️ REQUIRED for cookies!
    allow_methods=["*"],
    allow_headers=["*"],
)

# fsd.install(router)


# app.add_middleware(
#     auth.auth_incoming_req(call_next)
# )
app.include_router(router)
@app.get("/")
async def welcome():
    return {"message": "Welcome to Queue RX!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)