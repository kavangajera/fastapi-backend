# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Queue RX** — FastAPI backend for pharmacy queue management. Two halves run together:

1. **HTTP API** (`main.py`) — auth, pharmacy/user CRUD, manual entry, reports, plus a synchronous-feeling upload endpoint that actually offloads work to Kafka.
2. **Kafka workers** (`kafka_worker/`) — one process per `ProcessType` (`dispense`, `invoice`, `barcode`) that consumes its dedicated topic family, runs OCR / LLM extraction, and publishes results back.

Python ≥ 3.10, SQLAlchemy + Alembic on PostgreSQL, `aiokafka`, `loguru`, dependency management via `uv`.

## Common commands

```bash
# Dependencies (uv auto-creates .venv)
uv sync
uv add <package>

# Run the API
uv run main.py                                 # main.py runs uvicorn on :5001 with reload
uvicorn main:app --host 0.0.0.0 --port 5001    # alt

# Kafka (dev infra: zookeeper, broker on :9092, kafka-ui on :8080)
docker compose -f docker-compose.kafka.yml up -d

# Workers — ONE process per ProcessType, scale by launching more instances
python -m kafka_worker.run --type invoice
python -m kafka_worker.run --type dispense
python -m kafka_worker.run --type barcode

# Alembic
alembic revision --autogenerate -m "<message>"
alembic upgrade head
alembic downgrade -1
alembic current
```

There is no test suite or lint config in this repo — don't invent commands.

Useful URLs when the API is up:
- `http://localhost:5001/docs` — custom Swagger (default `/docs` is disabled and re-served from `main.custom_swagger_ui_html` with a JS injection for `/barcode/verify-batch` multi-file upload)
- `http://localhost:5001/dashboard` — `public/dashboard.html` served as-is for the monitor UI
- `http://localhost:8080` — kafka-ui

## Architecture

### Configuration & env

- `core/config.py` defines `Settings` (pydantic-settings, `extra="forbid"`, `.env`). Adding a new env var requires adding it to the `Settings` model — unknown keys raise. `PROVIDER` env var maps to `INVOICE_PROVIDER`.
- `database.py` (project root, **not** `core/database.py` — the README is out of date) holds the SQLAlchemy engine, `SessionLocal`, `Base`, and `get_db()` dependency. Workers import `SessionLocal` directly to manage their own sessions.

### HTTP layer

- `main.py` builds the FastAPI app, registers exception handlers that normalize errors into `{status_code, message, data}`, mounts CORS (`*`), and `include_router`s for: top-level `router` (`routes/__init__.py`, contains auth/user/pharmacy), `pharmacy_purchase_report`, `barcode`, `invoice`, `manual_entry`, `documents`, `monitor`.
- `routes/__init__.py` is unusual: instead of `APIRouter()` per file with decorators, it builds one shared router using `router.add_api_route(...)` so it can attach rich OpenAPI metadata (summary, description, response_model, operation_id) declaratively. Mirror this pattern when adding endpoints to that aggregate router; the standalone routers (`documents`, `monitor`, etc.) use the conventional `@router.get(...)` style.
- Auth: `middlewares/auth.py::auth_incoming_req` is a dependency (not a Starlette middleware) — `Depends(auth_incoming_req)` on a route validates the Bearer JWT and returns a `System_Internal_User_Schema`. JWTs are created in `core/security_schemes.py` (HS256, settings-driven expiry). Refresh tokens are returned as httpOnly cookies and exchanged via `GET /user/renew-access-token`.
- Roles (`core/enums.UserRole`): `OWNER`, `TECHNICIAN`, `ADMIN`. Role gating happens inside service functions, not via decorator — check existing services before adding new endpoints.
- **Signup is OTP-gated.** `POST /user/signup` does *not* create an account — it stages credentials in `pending_signup` and mails a code; `POST /user/verify-signup-otp` is the only endpoint that inserts a `user` row. `user_service` deliberately exposes no function that creates a user from a raw payload — only `create_verified_user`, whose sole caller is `services/signup_service.py`. Keep it that way: adding an un-gated create path silently removes email verification from the product. (Technicians are exempt — `POST /user/create-technician` is called by an already-authenticated owner.)

### Document processing pipeline (Kafka)

This is the non-obvious part of the codebase. Read this before touching anything under `kafka_infra/`, `kafka_worker/`, or `routes/documents.py`.

**Topic naming is derived, not configured.** `kafka_infra/topics.py` generates names from `ProcessType`:

```
<type>-processing   main job topic       (consumed by the <type> worker)
<type>-retry        delayed retry topic  (consumed by the retry consumer)
<type>-dlq          dead letter queue    (terminal failures)
processing-results  shared results topic (worker → API result bus)
```

Consumer groups follow the same pattern: `<type>-workers`, `<type>-retry-workers`. Adding a new `ProcessType` automatically reserves four topics; you must also (a) extend `ALLOWED_EXTENSIONS` in `core/enums.py` and (b) register a handler in `kafka_worker/handlers/__init__.py::HANDLERS`.

**Upload flow** (`POST /documents/process`, in `routes/documents.py`):

1. Validate extension against `ALLOWED_EXTENSIONS[process_type]` and size against `DOCUMENT_MAX_FILE_SIZE_MB`.
2. Write bytes to `storage/documents/{doc_key}.{ext}` via `services/document_storage.py`.
3. Insert a `Document` row with status `QUEUED`.
4. **Register an `asyncio.Future` with `result_bus.register(doc_key)` BEFORE publishing** — otherwise the worker can publish a result before the API is listening.
5. Publish a `ProcessingJob` to `<type>-processing`.
6. `await asyncio.wait_for(future, timeout=PROCESSING_RESULT_TIMEOUT_SECONDS)` — push-based, no polling. On timeout, return `202`-style `QUEUED` response and let the client poll `GET /documents/{doc_key}`.

**Worker flow** (`kafka_worker/base_worker.py`):

- `enable_auto_commit=False`; the consumer commits offset **only after** the outcome is durably handed off (result published, retry scheduled, or DLQ written). Don't change this — it's the safety guarantee that lets us run blocking handlers.
- `max_poll_interval_ms=600_000` to tolerate long OCR / LLM calls.
- Handlers are sync `(db, doc) -> dict` callables; the worker runs them via `asyncio.to_thread` so the event loop stays free for Kafka heartbeats.
- Idempotency: terminal docs (`COMPLETED` / `FAILED_PERMANENTLY`) are skipped on replay.
- Failure path: `attempt < DOCUMENT_MAX_RETRIES` → republish to `<type>-retry` with `process_after = now + base * 2^(attempt-1)` seconds; the `RetryConsumer` waits until `process_after` then re-injects onto `<type>-processing`. Exhausted → DLQ + `FAILED_PERMANENTLY` result.

**Result bus** (`kafka_infra/result_bus.py`):

- Each API instance joins `processing-results` with a **unique** consumer group (`api-results-<uuid8>`) and `auto_offset_reset="latest"` — every instance sees every result and resolves only the `doc_key`s it's locally awaiting. This is broadcast-by-design; don't try to share a group.
- Started/stopped in the FastAPI `lifespan`. Kafka being unavailable at startup is logged as a warning, not fatal — but `/documents/process` will then 503.

### Models & migrations

- `models/__init__.py` re-exports every model. `alembic/env.py` does `from models import *` so any model not registered here is invisible to `--autogenerate`. **When you add a model, add it to `models/__init__.py` or migrations will silently miss it.**
- Migration history shows some duplicate-named revisions (`15863dc71268` and `832c883595c3` both named `add_invoices_reconciliation_and_limits`, and `2a898550855b` / `c967a7f570eb` for the relationship change). Inspect `down_revision` chains before writing a new migration.
- The `Document` table tracks the Kafka pipeline state machine (`DocumentStatus` enum in `core/enums.py`): `UPLOADED → QUEUED → PROCESSING → COMPLETED | FAILED → RETRYING → FAILED_PERMANENTLY`.

### Logging

`core/logging.py::setup_logging()` is called once at module import in `main.py`. It removes default loguru handlers and adds three sinks: stderr, a timestamped file in `LOG_DIR` (default `logs/`), and an in-memory ring buffer (`core/log_buffer.py`) that powers the monitor dashboard's live log stream. Workers call `setup_logging()` themselves in `kafka_worker/run.py`.

### Storage

Uploaded files live on local disk at `DOCUMENT_STORAGE_DIR` (default `storage/documents/`). `services/document_storage.py` is intentionally abstracted so it can be swapped for S3/MinIO later — keep callers using the `document_storage` singleton, not direct filesystem calls.

## Conventions worth knowing

- Error responses are normalized to `{status_code, message, data}` by handlers in `main.py`. If a service raises `HTTPException(detail={"status_code": ..., ...})`, the dict is passed through verbatim; otherwise `detail` becomes `message`.
- `database.py` is imported as `from database import get_db, SessionLocal` — it lives at the project root, not under `core/`. Don't move it without updating ~20 import sites.
- The custom `/docs` endpoint injects JavaScript to add a multi-file upload widget specifically for `/barcode/verify-batch`. If you edit Swagger setup, preserve that injection or that endpoint becomes hard to use from the UI.
- `vercel.json` exists but the Kafka-based pipeline makes Vercel deployment infeasible for the worker side; treat the API as standalone-deployable only.
- README.md is comprehensive but predates the Kafka pipeline rewrite — trust the code over the README when they disagree (notably: `database.py` location, port `5001` not `8000`/`8443`, presence of `kafka_infra` / `kafka_worker` / `routes/documents.py`).
