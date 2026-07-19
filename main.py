from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger

from core.logging import setup_logging
from kafka_infra import topics
from kafka_infra.producer import kafka_producer
from kafka_infra.result_bus import result_bus
from routes import router
from routes.activity import router as activity_router
from routes.admin_subscription import router as admin_subscription_router
from routes.audit_report import router as audit_report_router
from routes.dispense_save import router as dispense_save_router
from routes.dispense_validate import router as dispense_validate_router
from routes.documents import router as documents_router
from routes.inventory import router as inventory_router
from routes.invoice import router as invoice_router
from routes.invoice_save import router as invoice_save_router
from routes.monitor import router as monitor_router
from routes.pharmacy_purchase_report import router as report_router
from routes.reconciliation import router as reconciliation_router
from routes.refills import router as refills_router
from routes.stripe_webhook import router as stripe_webhook_router
from routes.subscription import router as subscription_router
from routes.temperature_logs import router as temperature_logs_router
from schemas.response_schema import success_response

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage Kafka producer + result-bus lifecycle for the async-await UX."""
    try:
        await topics.ensure_topics()
    except Exception as exc:
        logger.warning("Kafka topic ensure failed at startup: {error}", error=exc)
    try:
        await kafka_producer.start()
        await result_bus.start()
    except Exception as exc:
        logger.warning(
            "Kafka unavailable at startup: {error}. "
            "Document processing will not work until Kafka is reachable.",
            error=exc,
        )
    yield
    try:
        await result_bus.stop()
    except Exception:
        pass
    try:
        await kafka_producer.stop()
    except Exception:
        pass


app = FastAPI(
    title="Queue RX API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
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
            "name": "Admin",
            "description": "Endpoints restricted to users with the ADMIN role for platform-wide management.",
        },
        {
            "name": "Document Processing",
            "description": "Upload a single document (or 2 barcode images) for extraction. The endpoint returns parsed JSON only; nothing is written to invoices/drug_reports.",
        },
        {
            "name": "Invoices",
            "description": "POST /invoices to persist a (possibly user-edited) invoice JSON. Persistence triggers a +qty update on medicine_inventory.",
        },
        {
            "name": "Dispense Reports",
            "description": "POST /dispenses to persist a (possibly user-edited) dispense report JSON. Persistence triggers a -qty update on medicine_inventory.",
        },
        {
            "name": "Inventory",
            "description": "Per-medical-store running stock, keyed by (medical_store_id, ndc11 or upc).",
        },
        {
            "name": "Temperature Logs",
            "description": "Basic connectivity surface for external temperature devices to store and read back temperature logs.",
        },
    ],
    lifespan=lifespan,
)


@app.get("/docs", include_in_schema=False)
def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title="Queue RX API Docs",
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
        status_code=422,
        content={
            "status_code": 422,
            "message": f"Validation Error: {combined_message}",
            "data": None,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "status_code" in exc.detail:
        return JSONResponse(
            status_code=exc.detail.get("status_code", exc.status_code), content=exc.detail
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={"status_code": exc.status_code, "message": str(exc.detail), "data": None},
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
app.include_router(invoice_router)
app.include_router(documents_router)
app.include_router(invoice_save_router)
app.include_router(dispense_save_router)
app.include_router(dispense_validate_router)
app.include_router(inventory_router)
app.include_router(activity_router)
app.include_router(audit_report_router)
app.include_router(refills_router)
app.include_router(monitor_router)
app.include_router(subscription_router)
app.include_router(admin_subscription_router)
app.include_router(reconciliation_router)
app.include_router(temperature_logs_router)
app.include_router(stripe_webhook_router)


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_view():
    import asyncio
    import os

    file_path = os.path.join(os.path.dirname(__file__), "public", "dashboard.html")

    def _read() -> str:
        with open(file_path, encoding="utf-8") as f:
            return f.read()

    try:
        html_content = await asyncio.to_thread(_read)
        return HTMLResponse(content=html_content, status_code=200)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard UI not found") from None


@app.get("/")
async def welcome():
    return success_response({"message": "Welcome to Queue RX!"}, "Welcome to Queue RX!")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)
