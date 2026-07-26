# API Reference

> Audience: frontend devs binding to the backend, Postman / Swagger
> testers, and anyone debugging "why is this 422".
>
> All routes are served by `main.py` on `:5001`. Swagger UI lives at
> `GET /docs`. Every protected route requires a `Authorization: Bearer
> <access_token>` header obtained from `POST /user/login`.

## Conventions

- **Bodies** are JSON unless explicitly multipart (`POST /documents/process`).
- **Success envelope** for AUTH/USER/PHARMACY routes:
  `{ "status_code": 200, "message": "...", "data": ... }`. Other routes
  (documents, invoices, dispenses, inventory, monitor) return the data
  object directly with FastAPI's default `response_model`.
- **Error envelope** (any route):
  `{ "status_code": <code>, "message": "...", "data": null }`. Pydantic
  validation errors come back as `422` with a `Validation Error: ...`
  message naming the failing field.
- **Id field naming**: response bodies expose primary keys with a
  table-prefixed name, never a bare `id` — `user_id`, `pharmacy_id`,
  `invoice_id`, `report_id`, `medicine_id`, `dispense_id`,
  `line_item_id`, `summary_id`, `activity_id`. The pharmacy is always
  `pharmacy_id` in responses (the DB column is still `medical_store_id`;
  it is aliased on the way out). **Request bodies are unchanged** — they
  still take `medical_store_id` (e.g. create-technician, `/documents/process`,
  `/invoices`, `/dispenses`).
- **Role gating**: every endpoint that touches a pharmacy / medical
  store goes through `services/pharmacy_authz.py::ensure_pharmacy_access`
  — `ADMIN` allowed everywhere, `PHARMACY_OWNER` only on stores they
  own, `TECHNICIAN` only on their assigned `User.medical_store_id`.
- **PHI safety (spec §13)**: alerts and logs carry hashed `patient_key`
  + a light label (`"CEDENO, B."`); raw patient name/phone/address never
  leave the DB.

## Endpoint matrix

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` | — | welcome ping |
| GET | `/docs` | — | Swagger UI |
| GET | `/openapi.json` | — | OpenAPI spec |
| GET | `/dashboard` | — | served HTML monitor UI |
| POST | `/user/signup` | — | start signup, email a verification code (creates nothing) |
| POST | `/user/verify-signup-otp` | — | redeem the code → creates the OWNER account |
| POST | `/user/resend-signup-otp` | — | re-send the signup code |
| POST | `/user/login` | — | obtain access token + refresh cookie |
| GET | `/user/renew-access-token` | refresh cookie | new access token |
| GET | `/user/me` | bearer | own profile |
| PUT | `/user/update/me` | bearer | edit own profile |
| DELETE | `/user/delete/me` | bearer | delete own account |
| POST | `/user/create-technician` | bearer (OWNER/ADMIN) | create TECHNICIAN under a store |
| POST | `/user/get-technician` | bearer (OWNER/ADMIN) | list technicians |
| PUT | `/user/update/{user_id}` | bearer | edit a user (admin or self/own-tech) |
| DELETE | `/user/delete/{user_id}` | bearer | delete a user |
| GET | `/user/all` | bearer (ADMIN) | list all users |
| GET | `/user/by-email` | bearer (ADMIN) | lookup by email |
| GET | `/user/by-role` | bearer (ADMIN) | lookup by role |
| POST | `/pharmacy/create-pharmacy` | bearer (OWNER/ADMIN) | new medical store |
| GET | `/pharmacy/get-pharmacy` | bearer (OWNER/ADMIN) | list stores |
| GET | `/pharmacy/get-pharmacy-by-owner` | bearer (ADMIN) | stores by owner id |
| GET | `/pharmacy/by-name` | bearer (OWNER/ADMIN) | search by name |
| PUT | `/pharmacy/update/{ph_id}` | bearer (OWNER/ADMIN) | edit store |
| DELETE | `/pharmacy/delete/{ph_id}` | bearer (OWNER/ADMIN) | delete store |
| POST | `/documents/process` | bearer | upload + extract (NO domain writes) |
| GET | `/documents/{doc_key}` | bearer | check processing status |
| GET | `/documents/` | bearer | paginated list of documents |
| POST | `/invoices` | bearer | persist invoice JSON, +inventory |
| GET | `/invoices/` | bearer | list invoices (store-scoped) |
| GET | `/invoices/{invoice_id}` | bearer | invoice detail |
| POST | `/dispenses/validate` | bearer | run Tier-1+Tier-2 validation, no write |
| POST | `/dispenses` | bearer | validate + persist dispense JSON, -inventory |
| GET | `/reports/` | bearer | list drug reports (store-scoped) |
| GET | `/reports/{report_id}` | bearer | report detail (with medicines + dispenses) |
| GET | `/reports/{report_id}/medicines/{ndc}` | bearer | one medicine in a report |
| DELETE | `/reports/{report_id}` | bearer | delete a report |
| GET | `/pharmacy/{ph_id}/inventory` | bearer | running stock for a store |
| GET | `/api/monitor/*` | — | dashboard endpoints (overview, services, alerts, etc.) |

---

## Auth

### Signup — two steps, email-verified

Registration requires proof that the applicant controls the address.
`POST /user/signup` **does not create an account**; it stages the
credentials in `pending_signup` and mails a 6-digit code. The account
exists only once `POST /user/verify-signup-otp` succeeds. There is no
other code path that writes a `user` row (technicians excepted — those are
created by an already-authenticated owner via `/user/create-technician`).

#### `POST /user/signup` — step 1

Email must be unique (409 if taken) and the password at least 8
characters. The password is Argon2id-hashed on arrival and is never stored
in the clear, not even while pending.

**Body**
```json
{
  "user_email": "owner@example.com",
  "input_password": "Secret123!",
  "device_id": "a1B2c3"
}
```

**200 (envelope)**
```json
{ "status_code": 200,
  "message": "A verification code has been sent to owner@example.com. Enter it to finish creating your account.",
  "data": { "email_sent": true, "user_email": "owner@example.com",
            "expires_in_minutes": 15,
            "message": "A verification code has been sent to owner@example.com. Enter it to finish creating your account." } }
```

| Status | When |
|---|---|
| 409 | that email already has an account |
| 422 | password under 8 chars, or malformed email |
| 429 | another code was requested under 60s ago, 5 codes already sent for this signup, or the caller IP is over budget (`Retry-After` set) |

#### `POST /user/verify-signup-otp` — step 2 (creates the account)

**Body**
```json
{ "user_email": "owner@example.com", "otp_code": "482913", "device_id": "a1B2c3" }
```

**200 (envelope)**
```json
{ "status_code": 201, "message": "Email verified — account created successfully",
  "data": { "user_id": 1, "email": "owner@example.com", "role": "OWNER" } }
```

The staged signup is deleted in the same transaction that creates the
user, so the code cannot be replayed. A wrong code returns `400` with the
attempts remaining; after 5 failures — or once the code expires (15 min) —
the staged signup is discarded and signup must be started again (`404` on
the next attempt).

#### `POST /user/resend-signup-otp`

**Body**: `{ "user_email": "owner@example.com" }` — mails a fresh code for a
signup already in flight and invalidates the previous one. The password is
not resubmitted, so a resend cannot change it. `404` if nothing is pending
for that address; `429` while inside the cooldown or over the send cap.

### `POST /user/login`

**Body**
```json
{ "user_email": "owner@example.com", "input_password": "Secret123!" }
```

**200**
```json
{ "status_code": 200, "message": "Login successful",
  "data": { "access_token": "eyJ...", "user_id": 1, "email": "owner@example.com", "role": "OWNER" } }
```

Also sets the `refresh_token` httpOnly cookie. Access token expiry
(`ACCESS_TOKEN_EXPIRE_MINUTES`, default 5) — refresh via
`/user/renew-access-token`.

### `GET /user/renew-access-token`

Reads the `refresh_token` cookie and returns a fresh access token. No
body, no bearer required.

**200** `{ "data": { "access_token": "eyJ..." } }`

---

## User

### `POST /user/create-technician`

Owners create techs for stores they own. Admins can create anywhere.

**Body**
```json
{
  "user_name": "tech1",
  "user_email": "tech1@example.com",
  "contact": "9999999999",
  "input_password": "TechSecret!",
  "medical_store_id": 1
}
```

### `POST /user/get-technician`

Body-less / optional `ph_id` filter. Owners see techs of their own
stores; admins see all (optionally filtered).

### `GET /user/me`, `PUT /user/update/me`, `DELETE /user/delete/me`

Self-serve profile. `update` body accepts partial:

```json
{ "name": "New Name", "user_email": "new@example.com", "phone": "8888888888" }
```

### `PUT /user/update/{user_id}`, `DELETE /user/delete/{user_id}`

Admin can target anyone. Owner can target self or technicians of own
stores. Technicians must use `/me` instead.

### `GET /user/all`, `/user/by-email?user_email=...`, `/user/by-role?role=OWNER`

Admin-only listing/search endpoints. 403 for other roles.

---

## Pharmacy / medical store

### `POST /pharmacy/create-pharmacy`

```json
{ "pharmacy_title": "My Store", "pharmacy_location": "Brooklyn NY 11226" }
```

**201** returns `{ data: { pharmacy_id: 1, name, address, owner: { user_id, email, role } } }`.

### `GET /pharmacy/get-pharmacy?ph_id=`

- Admin → all stores (optionally filtered by `ph_id`), with `owner` field populated.
- Owner → own stores; `owner` field nulled out for privacy.
- Technician → 403.

The `owner` field is eager-loaded — see `data_model.md` §"Async
pitfalls" for the reason.

### `GET /pharmacy/get-pharmacy-by-owner?owner_id=`

ADMIN only. Returns every store owned by `owner_id`.

### `GET /pharmacy/by-name?name=Deva`

Case-insensitive partial match. Owner sees only own.

### `PUT /pharmacy/update/{ph_id}`

```json
{ "pharmacy_title": "New Name", "pharmacy_location": "..." }
```

### `DELETE /pharmacy/delete/{ph_id}`

Irreversible. Cascades to documents/invoices/drug_reports/inventory via
FK CASCADE.

---

## Documents — extraction pipeline

### `POST /documents/process`

The only upload endpoint. Sends file(s) through the Kafka pipeline,
which extracts structured JSON and returns it inline. **No domain rows
in `invoices` / `drug_reports` are created.** Save flow happens via
`POST /invoices` and `POST /dispenses`.

**Form fields** (multipart):

| Field | Type | Notes |
|---|---|---|
| `process_type` | enum | `invoice` / `dispense` / `barcode` |
| `medical_store_id` | int | required; ownership-checked |
| `files` | List[file] | **exactly 1** for `invoice`/`dispense`; **1 or 2** for `barcode` (so barcode + datamatrix can be in separate images) |

**File extension restrictions** (`core.enums.ALLOWED_EXTENSIONS`):

| process_type | allowed |
|---|---|
| `invoice` | `pdf` |
| `dispense` | `pdf`, `docx`, `doc`, `xlsx`, `xls` |
| `barcode` | `png`, `jpg`, `jpeg`, `heic`, `heif` |

**200 happy path**:
```json
{
  "doc_key": "7d902...",
  "process_type": "dispense",
  "status": "COMPLETED",
  "message": "Document processed successfully.",
  "data": {
    /* extracted fields, shape depends on process_type. For dispense it
       carries pharmacy/medicines/grand_total + a fully-formed
       validation block (Tier 1 only).
       For invoice it carries seller/customer/line_items/summary.
       For barcode it carries {matched: [...], unmatched: [...]}. */
  }
}
```

**Timeout**: if processing exceeds `PROCESSING_RESULT_TIMEOUT_SECONDS`
(default 180 s) the response comes back with `status: "QUEUED"` and no
`data` — the client should poll `GET /documents/{doc_key}` until status
flips to `COMPLETED` / `FAILED_PERMANENTLY`.

**Common errors**:

| Status | Cause |
|---|---|
| 400 | wrong file count for the process_type, unsupported extension, empty file |
| 403 | medical_store_id not owned by caller |
| 413 | file size > `DOCUMENT_MAX_FILE_SIZE_MB` |
| 503 | Kafka broker unreachable |

### `GET /documents/{doc_key}`

Returns the `documents` row including the JSON-stringified `result_data`.
Caller-scoped: returns 403 if `doc.medical_store_id` isn't yours.

### `GET /documents/?skip=0&limit=50`

Paginated list. Owner/Technician sees their stores' documents; Admin
sees all.

---

## Invoices

### `POST /invoices`

Strict schema (`schemas/save_invoice.py`, `extra="forbid"`). Body shape
matches the `data` block returned by `process?process_type=invoice`
exactly — you can `data → body` with no transformation.

**Body** (representative)
```json
{
  "medical_store_id": 1,
  "document_id": 1,
  "source_filename": "Kinray 1.pdf",
  "page_count": 1,
  "seller_name": "KINRAY",
  "invoice_number": "7461351597",
  "invoice_date": "02/18/2026",
  "due_date": "03/25/2026",
  "line_items": [
    {
      "line": "30", "item_code": "5752290",
      "ndc": "72888000901", "lot_number": "2097749781",
      "invoiced_qty": "1", "uom": "ea",
      "description": "BACLOFEN TB 5MG 100",
      "unit_price": "6.81", "extended_price": "6.81",
      "fda_package_ndc": null, "fda_ndc11": null,
      "dm_gtin": null, "dm_serial_number": null,
      "dm_expiration_date": null, "dm_lot_number": null,
      "verified": false
    }
  ],
  "summary": {
    "order_line_total": "122.01", "sub_total": "122.01",
    "tax": null, "grand_total": "122.01", "total_due_by": "03/25/2026"
  }
}
```

**201**
```json
{
  "invoice_id": 1,
  "pharmacy_id": 1,
  "line_items_created": 5,
  "summary_saved": true,
  "inventory_updates": [
    { "code": "72888000901", "delta": "1", "new_quantity": "1" },
    ...
  ]
}
```

`inventory_updates` echoes the `medicine_inventory` rows that were
incremented (or created). The `code` is `ndc11` if 11 digits, else `upc`.

**422**: schema violation (unknown field, missing required). 403:
ownership check failed.

### `GET /invoices/?skip=0&limit=50`

List, store-scoped.

### `GET /invoices/{invoice_id}`

Detail with `line_items` and `summary` populated.

---

## Dispenses & validation engine

### `POST /dispenses/validate`

Body shape identical to `POST /dispenses`. Runs **Tier 1 + Tier 2**
validation (FDA-backed Modules A, B, C plus all pure-data checks) and
returns a `ValidationReport`. **No DB writes.**

Use case: the UI calls this after each form edit to surface alerts
without committing.

**Response** (see `docs/validation_engine.md` for the full module
catalogue):
```json
{
  "summary": {
    "errors": 1, "warnings": 3, "info": 12, "indeterminate": 0,
    "blocking": true, "tier1_ran": true, "tier2_ran": true
  },
  "alerts": [
    { "module": "C", "code": "UNIT_OF_USE_FRACTIONAL",
      "severity": "ERROR", "medicine_index": 5, "dispense_index": 0,
      "ndc": "00310461612", "rx_no": "504850.0",
      "field": "qty_disp", "actual": "32.1",
      "suggestion": "Set qty_disp to a whole number of packages/units." }
  ],
  "grand_total": { "printed_rx_count": 99, "recomputed_rx_count": 98, ... },
  "per_patient": [ { "patient_key": "16a955...", "patient_label": "ESPOSITO, F.", "rx_count": 1, "total_price": "4471.68", ... } ]
}
```

First call against a new set of NDCs takes ~30–60 s (FDA HTTP); cached
calls (within `NDC_CACHE_TTL_DAYS`, default 7) are sub-second.

### `POST /dispenses`

Same body. **Validates first**; if any `ERROR`-severity alert is
present, returns **422 with the full `ValidationReport` in
`detail.data`**, writes nothing.

Otherwise:
1. Inserts `DrugReport` + N `Medicine` + M `Dispense` rows.
2. Calls `subtract_dispense_quantities`: per medicine,
   `−sum(qty_disp)` upsert into `medicine_inventory`.
3. Returns `DispenseSaveResponse` (with `validation` block of remaining
   warnings/info attached).

**Body** (representative)
```json
{
  "medical_store_id": 1,
  "document_id": 1,
  "pharmacy": {
    "pharmacy_name": "Good Health Pharmacy",
    "address": "1379-83 Nostrand Ave, Brooklyn, NY 11226",
    "phone": "(718)618-7425", "fax": "(718)618-7428",
    "report_date": "2/1/2026",
    "report_from_date": "1/30/2026", "report_to_date": "2/1/2026"
  },
  "grand_total": {
    "total_price": "29832.03", "total_rx_count": "99", "total_cost": "45579.93"
  },
  "medicines": [
    {
      "drug_name": "ALBUTEROL SULFATE 0.083% SOL",
      "ndc": "76204020025",
      "totals": { "packs": "1.000", "total_rx_count": "1",
                  "total_ins_paid": "14.59", "total_price": "14.59" },
      "dispenses": [
        {
          "qty_disp": "75.000", "qty_ord": "75.000",
          "days_supply": 5, "date_filled": "01/30/2026",
          "rx_no": "507979", "ref": "1",
          "pat_name": "CEDENO, BRANDON",
          "pat_addr": "221 LINDEN BLVD #D1 Brooklyn NY 11213",
          "pat_phone": "7183046460",
          "pres_name": "HOWARD, CARLA",
          "pres_addr": "2094 PITKIN AVENUE BROOKLYN NY 11207",
          "pres_phone": "7182400400",
          "price": "14.59", "ins_paid": "14.59", "ins_code": "MCD"
        }
      ]
    }
  ]
}
```

**201**
```json
{
  "report_id": 1,
  "pharmacy_id": 1,
  "medicines_saved": 86,
  "dispenses_saved": 98,
  "inventory_updates": [
    { "code": "76204020025", "delta": "-75.000", "new_quantity": "-75.000" }
  ],
  "validation": { /* same shape as /validate */ }
}
```

**422 (blocked)**
```json
{
  "detail": {
    "status_code": 422,
    "message": "Dispense save blocked by 4 validation error(s). Fix the listed issues and resubmit.",
    "data": { /* full ValidationReport */ }
  }
}
```

---

## Drug reports (read-side)

### `GET /reports/?skip=0&limit=50`

Lightweight list — owner/tech sees their stores, admin sees all.

### `GET /reports/{report_id}`

Full report: `DrugReport` + `medicines[]` + each `medicine.dispenses[]`.
All eager-loaded via `lazy="selectin"`.

### `GET /reports/{report_id}/medicines/{ndc}`

One medicine in the context of one report (cheap lookup for drilling
into a specific drug).

### `DELETE /reports/{report_id}`

Removes report + medicines + dispenses via FK CASCADE. Does NOT
unwind inventory changes — manual data fix only.

---

## Inventory

### `GET /pharmacy/{ph_id}/inventory`

```json
{
  "pharmacy_id": 1,
  "items": [
    { "code": "72888000901", "product_name": "BACLOFEN TB 5MG 100",
      "quantity": "-30.000", "last_invoice_id": 1,
      "updated_at": "2026-06-13T12:00:00" }
  ],
  "total": 12
}
```

Sorted by `code`. Negative `quantity` = dispensed without a matching
invoice (UI shows "missing invoice" warning).

---

## Monitor (dashboard)

Endpoints under `/api/monitor/*` power the HTML dashboard at
`/dashboard`. All read-only. Not pharmacy-scoped — built for backend
operators.

| Path | Returns |
|---|---|
| `/overview` | counts by status, throughput stats, success rate |
| `/services` | health probe of API/DB/Kafka/storage/worker |
| `/documents/recent?limit=30` | latest documents across all stores |
| `/documents/by-status` | `{status: count, ...}` |
| `/documents/by-type` | `{document_type: count, ...}` |
| `/documents/timeline?hours=24` | hourly completed/failed/queued buckets |
| `/alerts` | computed operational alerts (queue depth, error rate, stale processing, kafka down) |
| `/config` | non-sensitive runtime config |
| `/metrics` | uptime, mem, disk, gc |
| `/logs?limit=100&level=INFO` | in-memory ring buffer from `core/log_buffer.py` |

---

## Working test sequence (end to end)

For a fresh clean run on dispense:

```bash
# 1. Signup (2 steps — the code arrives by email; with no SMTP configured
#    it is written to the log instead) + login (capture access_token)
POST /user/signup             { user_email, input_password }   → code mailed
POST /user/verify-signup-otp  { user_email, otp_code }         → account created
POST /user/login              { user_email, input_password }   → access_token
# Click "Authorize" in Swagger and paste the token.

# 2. Create a store
POST /pharmacy/create-pharmacy   { pharmacy_title, pharmacy_location }
                                                       → pharmacy_id

# 3. Upload + extract a dispense PDF
POST /documents/process
  process_type=dispense
  medical_store_id=<id>
  files=<sample 01.pdf>
                                                       → data.{...} + data.validation

# 4a. (Optional) dry-run validation including FDA
POST /dispenses/validate   { ...data block from step 3 }
                                                       → ValidationReport

# 4b. Save
POST /dispenses            { ...data block from step 3 }
                                                       → 201 with inventory_updates
                                                          OR 422 with alerts to fix

# 5. Check current stock
GET /pharmacy/<id>/inventory
                                                       → running quantities
```

For invoice flow:

```bash
POST /documents/process   process_type=invoice  files=Kinray-1.pdf  → data.{...}
POST /invoices            { ...data block }                         → 201 + inventory_updates
```

For barcode flow (per-medicine verification, optional within invoice flow):

```bash
POST /documents/process   process_type=barcode  files=[img1.heic, img2.heic]
                                                                    → data.matched[0]
# Then splice matched[0]'s fda_*/dm_* fields into the corresponding
# line_item of the invoice JSON before POST /invoices.
```

---

## Status code key

| Code | What it means here |
|---|---|
| 200 | OK |
| 201 | row created |
| 400 | malformed request (wrong file count, unsupported extension, etc.) |
| 401 | missing/invalid/expired bearer token |
| 403 | role / ownership check failed (`ensure_pharmacy_access`) |
| 404 | row not found |
| 413 | file too large |
| 422 | Pydantic validation, OR dispense validation engine blocked save |
| 500 | unhandled exception (logged via loguru) |
| 503 | Kafka broker / FDA unreachable |
