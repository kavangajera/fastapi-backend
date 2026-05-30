from fastapi import FastAPI, APIRouter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi import HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.middleware.cors import CORSMiddleware
from core.config import settings
from core.logging import setup_logging
from routes import router
from routes.pharmacy_purchase_report import router as report_router
from routes.barcode import router as barcode_router
from routes.invoice import router as invoice_router
from routes.manual_entry import router as manual_entry_router
from middlewares import auth

setup_logging()
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
            "name": "Manual Data Entry",
            "description": "Endpoints for manually entering invoice and dispense data via JSON instead of document upload.",
        },
    ],
)


@app.get("/docs", include_in_schema=False)
def custom_swagger_ui_html():
        swagger_ui = get_swagger_ui_html(
                openapi_url=app.openapi_url,
                title="Queue RX API Docs",
        )
        html = swagger_ui.body.decode("utf-8")

        inject = """
<script>
function setupBarcodeMultiUpload() {
    const opBlocks = document.querySelectorAll('.opblock');
    opBlocks.forEach(block => {
        const summary = block.querySelector('.opblock-summary-path');
        if (!summary || !summary.textContent) return;
        if (!summary.textContent.includes('/barcode/verify-batch')) return;

        const body = block.querySelector('.opblock-body');
        if (!body) return;

        const addButtons = body.querySelectorAll('button');
        addButtons.forEach(btn => {
            if (btn.textContent && btn.textContent.toLowerCase().includes('add string item')) {
                btn.style.display = 'none';
            }
        });

        if (body.querySelector('.barcode-multi-upload')) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'barcode-multi-upload';
        wrapper.style.margin = '12px 0';
        wrapper.innerHTML = `
            <div style="font-weight:600; margin-bottom:6px;">Multi-file upload</div>
            <input type="file" id="barcode-multi-input" multiple />
            <button type="button" id="barcode-multi-submit" style="margin-left:8px;">Upload</button>
            <pre id="barcode-multi-output" style="margin-top:8px; white-space:pre-wrap;"></pre>
        `;
        body.prepend(wrapper);

        const input = wrapper.querySelector('#barcode-multi-input');
        const button = wrapper.querySelector('#barcode-multi-submit');
        const output = wrapper.querySelector('#barcode-multi-output');

        button.addEventListener('click', async () => {
            if (!input || !input.files || input.files.length === 0) {
                output.textContent = 'Select one or more files first.';
                return;
            }
            const formData = new FormData();
            Array.from(input.files).forEach(file => formData.append('files', file));

            output.textContent = 'Uploading...';
            try {
                const res = await fetch('/barcode/verify-batch', {
                    method: 'POST',
                    body: formData,
                });
                const text = await res.text();
                output.textContent = text;
            } catch (err) {
                output.textContent = 'Upload failed: ' + err;
            }
        });
    });
}

window.addEventListener('load', () => {
    const interval = setInterval(() => {
        setupBarcodeMultiUpload();
    }, 500);
});
</script>
"""
        html = html.replace("</body>", inject + "</body>")
        return HTMLResponse(html)

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
        return JSONResponse(status_code=exc.detail.get("status_code", exc.status_code), content=exc.detail)
    
    return JSONResponse(
        status_code=exc.status_code,
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
app.include_router(barcode_router)
app.include_router(invoice_router)
app.include_router(manual_entry_router)
@app.get("/")
async def welcome():
    return {"message": "Welcome to Queue RX!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)