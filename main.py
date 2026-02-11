from fastapi import FastAPI, APIRouter
import fastapi_swagger_dark as fsd
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from core.config import settings

app = FastAPI(docs_url=None)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL
    ],
    allow_credentials=True,  # ⚠️ REQUIRED for cookies!
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter()
fsd.install(router)
app.include_router(router)

@app.get("/")
async def welcome():
    return {"message": "Welcome to Queue RX!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)