# API Reference

> Audience: frontend devs binding to the backend, Postman / Swagger
> testers, and anyone debugging "why is this 422".
>
> All routes are served by `main.py` on `:5001`. Swagger UI lives at
> `GET /docs` (custom-served — the default `/docs` is disabled and
> re-served via `main.custom_swagger_ui_html`, with a JS injection for a
> `/barcode`-style multi-file upload widget on `/documents/process`).
> Every protected route requires an `Authorization: Bearer <access_token>`
> header obtained from `POST /user/login`.

## Conventions

- **Bodies** are JSON unless explicitly multipart (`POST /documents/process`,
  `PATCH /dispenses/document`).
- **Envelope**: every response — success or error — is
  `schemas/response_schema.py::Response_Schema`:
  `{ "status_code": <int>, "message": "...", "data": ... }`. A handful of
  routes bypass the envelope entirely and return a raw dict/list: all of
  `GET /api/monitor/*` and `POST /webhooks/stripe`.
- **⚠ The envelope's `status_code` field is NOT always the real HTTP status.**
  Several routes are registered without an explicit FastAPI `status_code=`
  on the decorator (or via `router.add_api_route(...)` with none), so
  FastAPI's default (**200**) is what actually goes out on the wire even
  though the JSON body says `"status_code": 201`. Concretely:
  - Real HTTP status **differs from 200 on success** only for: `POST
    /invoices` (201), `POST /dispenses` (201). `PUT /dispenses/{report_id}`,
    `PATCH /dispenses`, and `PATCH /dispenses/document` explicitly set 200
    (matches default, no discrepancy).
  - Everywhere else — `POST /user/signup`, `POST /user/verify-signup-otp`,
    `POST /user/create-technician`, `POST /pharmacy/create-pharmacy`,
    `POST /admin/subscriptions`, `POST /admin/plans`, `POST
    /subscription/subscribe`, `POST /pharmacy/ownership-transfer/create`,
    `POST /temperature-logs`, and the "still processing" branch of `POST
    /documents/process` — the body's `status_code` says `201`/`202` but the
    **real HTTP status is 200**.
  - Error paths are not affected: every manually-raised `HTTPException`
    carries a real, correct HTTP status, and `main.py`'s exception handlers
    forward it (plus any `headers`, e.g. `Retry-After` on 429) verbatim.
  - **Bottom line**: don't branch client logic on the raw HTTP status
    for a "was this actually 201" question — read `data` / body
    `status_code` field, or just check `response.ok` and parse `data`.
- **Error envelope**: `{ "status_code": <code>, "message": "...", "data": null }`.
  `RequestValidationError` (malformed body/query) is caught globally and
  returns real HTTP `422` with `"message": "Validation Error: field: msg | ..."`
  naming every failing field. A raised `HTTPException(status_code=X,
  detail={"status_code":X,"message":...,"data":...})` is passed through
  verbatim by `main.py`'s handler; a bare `HTTPException(status_code=X,
  detail="...")` is normalized into `{status_code:X, message:"...", data:null}`.
- **Id field naming**: response bodies expose primary keys with a
  table-prefixed name, never a bare `id` — `user_id`, `pharmacy_id`,
  `invoice_id`, `report_id`, `medicine_id`, `dispense_id`, `line_item_id`,
  `summary_id`, `activity_id`, `transfer_id`, `subscription_id`, `plan_id`,
  `payment_id`, `temperature_log_id`. The pharmacy is always `pharmacy_id`
  in responses (the DB column is still `medical_store_id`; it is aliased
  on the way out via each schema's `validation_alias`/`alias`).
  **Request bodies are unchanged** — they still take `medical_store_id`
  everywhere (create-technician, `/documents/process`, `/invoices`,
  `/dispenses`, `/pharmacy/{ph_id}/inventory`, subscription/reconciliation
  endpoints, etc.).
- **Role gating**: every endpoint that touches a pharmacy / medical store
  goes through `services/pharmacy_authz.py::ensure_pharmacy_access` —
  `ADMIN` allowed everywhere, `PHARMACY_OWNER` only on stores they own,
  `TECHNICIAN` only on their assigned `User.medical_store_id`. Failure is
  always `403` with one of: `"You do not own this pharmacy"`, `"You are
  not assigned to this pharmacy"`, `"Not authorized for this pharmacy"`.
- **Feature (plan) gating**: many endpoints additionally call
  `services/feature_gate.py::ensure_feature(db, medical_store_id,
  Feature.X)` **after** `ensure_pharmacy_access` — see
  [Subscriptions & plan gating](#subscriptions--plan-gating) below. Failure
  is `402`, never `403`. List endpoints instead silently filter out
  non-entitled stores via `entitled_store_ids(...)` rather than erroring.
- **PHI safety**: alerts, logs, and refill worklists carry a hashed
  `patient_key` + a light label (e.g. `"CEDENO, B."`); raw patient
  name/phone/address never leave the DB except inside the dispense report
  the caller itself submitted. See `docs/validation_engine.md` §5.
- **Auth failure shapes** (any `bearer`-tagged route, via
  `middlewares/auth.py::auth_incoming_req`): a **missing/malformed**
  `Authorization` header → `403 "Not authenticated"` (raised by FastAPI's
  `HTTPBearer` itself, before the dependency body runs — note this is 403,
  not 401). An **expired** token → `401 "Access token has expired"`. An
  **invalid/tampered** token → `401 "Invalid access token"`. A
  **structurally valid token whose user no longer exists** → `404 "User
  not found"` (not 401 — the user row is looked up fresh on every request).
  `require_admin` (used by `/api/monitor/*`) additionally checks
  `role == ADMIN`, else `403 "Admin access required"`.

## Endpoint matrix

| Method | Path | Auth | Feature gate | Purpose |
|---|---|---|---|---|
| GET | `/` | — | — | welcome ping |
| GET | `/docs` | — | — | Swagger UI (custom) |
| GET | `/openapi.json` | — | — | OpenAPI spec |
| GET | `/dashboard` | — | — | served HTML monitor UI |
| POST | `/user/signup` | — | — | start signup, email a verification code (creates nothing) |
| POST | `/user/verify-signup-otp` | — | — | redeem the code → creates the OWNER account |
| POST | `/user/resend-signup-otp` | — | — | re-send the signup code |
| POST | `/user/login` | — | — | obtain access token + refresh cookie |
| POST | `/app/login` | — | — | same as login, plus the Argon2id password hash (offline mobile) |
| GET | `/user/renew-access-token` | refresh cookie | — | new access token |
| POST | `/user/logout` | bearer | — | mark IsLogout=1 (does not revoke refresh tokens) |
| POST | `/user/forgot-password` | — | — | mail a password-reset code (always 200, enumeration-safe) |
| POST | `/user/verify-reset-otp` | — | — | redeem the code → short-lived reset JWT |
| POST | `/user/reset-password` | — | — | spend the reset JWT → set new password, revoke all refresh tokens |
| POST | `/user/impersonate` | bearer (ADMIN) | — | mint an access token as another user |
| GET | `/user/me` | bearer | — | own profile |
| PUT | `/user/update/me` | bearer | — | edit own profile |
| DELETE | `/user/delete/me` | bearer | — | soft-delete own account |
| POST | `/user/create-technician` | bearer (OWNER/ADMIN) | — | create TECHNICIAN under a store |
| POST | `/user/get-technician` | bearer (OWNER/ADMIN) | — | list technicians (POST, query params) |
| PUT | `/user/update/{user_id}` | bearer | — | edit a user (admin, or owner on self/own-tech) |
| DELETE | `/user/delete/{user_id}` | bearer | — | soft-delete a user |
| GET | `/user/all` | bearer (ADMIN) | — | list all users |
| GET | `/user/by-email` | bearer (ADMIN) | — | lookup by email |
| GET | `/user/by-role` | bearer (ADMIN) | — | lookup by role |
| POST | `/pharmacy/create-pharmacy` | bearer (OWNER/ADMIN) | — | new medical store, owned by caller |
| GET | `/pharmacy/get-pharmacy` | bearer (OWNER/ADMIN) | — | list stores |
| GET | `/pharmacy/get-pharmacy-by-owner` | bearer (ADMIN) | — | stores by owner id |
| GET | `/pharmacy/by-name` | bearer (OWNER/ADMIN) | — | search by name |
| PUT | `/pharmacy/update/{ph_id}` | bearer (OWNER/ADMIN) | — | edit store |
| DELETE | `/pharmacy/delete/{ph_id}` | bearer (OWNER/ADMIN) | — | soft-delete store |
| POST | `/pharmacy/ownership-transfer/initiate` | bearer (OWNER) | — | OTP the current owner, step 1 of transfer |
| POST | `/pharmacy/ownership-transfer/create` | bearer (OWNER) | — | redeem OTP → create PENDING transfer |
| GET | `/pharmacy/ownership-transfer/outgoing` | bearer | — | transfers you initiated |
| GET | `/pharmacy/ownership-transfer/incoming` | bearer | — | transfers offered to you |
| GET | `/pharmacy/ownership-transfer/my` | bearer | — | both lists + pending count |
| POST | `/pharmacy/ownership-transfer/{id}/send-otp` | bearer (recipient) | — | OTP the recipient, step 2 |
| POST | `/pharmacy/ownership-transfer/{id}/accept` | bearer (recipient) | — | redeem OTP → flips `Pharmacy.user_id` |
| POST | `/pharmacy/ownership-transfer/{id}/reject` | bearer (recipient) | — | decline, no OTP |
| POST | `/pharmacy/ownership-transfer/{id}/cancel` | bearer (owner/ADMIN) | — | withdraw a pending request |
| GET | `/pharmacy/ownership-transfer/{id}` | bearer (either party/ADMIN) | — | transfer detail |
| GET | `/plans` | bearer | — | list active subscription plans |
| GET | `/subscription/{ph_id}` | bearer | — | current subscription for a store |
| POST | `/subscription/subscribe` | bearer (OWNER/ADMIN) | — | create Stripe Checkout Session |
| PUT | `/subscription/upgrade` | bearer (OWNER/ADMIN) | — | change plan via Stripe |
| POST | `/subscription/cancel` | bearer (OWNER/ADMIN) | — | cancel (legacy sync, or Stripe) |
| GET | `/subscription/{ph_id}/payments` | bearer | — | payment history |
| GET | `/admin/subscriptions` | bearer (ADMIN) | — | list/filter all subscriptions |
| POST | `/admin/subscriptions` | bearer (ADMIN) | — | upsert a subscription, bypasses Stripe |
| PUT | `/admin/subscriptions/{id}` | bearer (ADMIN) | — | edit a subscription, bypasses Stripe |
| POST | `/admin/subscriptions/{id}/revoke` | bearer (ADMIN) | — | immediate cancel |
| POST | `/admin/plans` | bearer (ADMIN) | — | create a plan |
| PUT | `/admin/plans/{id}` | bearer (ADMIN) | — | edit a plan |
| POST | `/webhooks/stripe` | signature | — | Stripe event ingestion (background-processed) |
| POST | `/documents/process` | bearer | per `process_type` | upload + extract (no domain writes) |
| GET | `/documents/{doc_key}` | bearer | per doc's `process_type` | check processing status |
| GET | `/documents/` | bearer | `INVENTORY_LITE` (non-admin filter) | paginated list of documents |
| GET | `/invoices/` | bearer | `INVOICE_TO_INVENTORY_AUTO` (filter) | list invoices (store-scoped) |
| GET | `/invoices/{invoice_id}` | bearer | `INVOICE_TO_INVENTORY_AUTO` | invoice detail |
| POST | `/invoices` | bearer | `INVOICE_TO_INVENTORY_AUTO` | persist invoice JSON, `+inventory` |
| POST | `/dispenses/validate` | bearer | `TOP_QUANTITY_DRUG_REPORT` | run Tier-1+Tier-2 validation, no write |
| POST | `/dispenses` | bearer | `TOP_QUANTITY_DRUG_REPORT` | validate + persist dispense JSON, `-inventory` |
| PUT | `/dispenses/{report_id}` | bearer | `TOP_QUANTITY_DRUG_REPORT` | full replace of a saved report |
| PATCH | `/dispenses` | bearer | `TOP_QUANTITY_DRUG_REPORT` | partial patch of existing dispenses by `rx_no` (no validation run) |
| PATCH | `/dispenses/document` | bearer | `TOP_QUANTITY_DRUG_REPORT` | patch existing dispenses from a re-uploaded corrected document |
| GET | `/reports/` | bearer | `TOP_QUANTITY_DRUG_REPORT` (filter) | list drug reports (store-scoped) |
| GET | `/reports/{report_id}` | bearer | `TOP_QUANTITY_DRUG_REPORT` | report detail (medicines + dispenses) |
| GET | `/reports/{report_id}/medicines/{ndc}` | bearer | `TOP_QUANTITY_DRUG_REPORT` | one medicine in a report |
| DELETE | `/reports/{report_id}` | bearer | `TOP_QUANTITY_DRUG_REPORT` | soft-delete a report |
| GET | `/pharmacy/{ph_id}/inventory` | bearer | `INVENTORY_LITE` | running stock for a store |
| GET | `/pharmacy/{ph_id}/inventory/{code}` | bearer | `INVENTORY_LITE` | one inventory row detail |
| PATCH | `/pharmacy/{ph_id}/inventory/{code}` | bearer (OWNER/ADMIN) | `INVENTORY_LITE` | absolute correction of a stock row |
| GET | `/pharmacy/{ph_id}/reconciliation/invoice-vs-billed` | bearer | `INVOICE_BILLED_CROSS_RECONCILIATION` | per-NDC purchased-vs-billed comparison |
| GET | `/pharmacy/{ph_id}/refills` | bearer | `REFILL_ANALYSIS_BILLINGS` | refill-due worklist |
| DELETE | `/pharmacy/{ph_id}/refills/{patient_key}` | bearer | `REFILL_ANALYSIS_BILLINGS` | dismiss a patient (all drugs or one NDC) from the worklist |
| GET | `/pharmacy/{ph_id}/activity` | bearer | `COMPLIANCE_REPORTS` | filterable activity/audit-log feed |
| GET | `/pharmacy/{ph_id}/audit-report` | bearer | `COMPLIANCE_REPORTS` | error-centric compliance summary |
| POST | `/temperature-logs` | — (public) | — | store readings from an external temperature device |
| GET | `/temperature-logs` | — (public) | — | read back stored readings |
| GET | `/api/monitor/*` | bearer (ADMIN) | — | dashboard endpoints (overview, services, alerts, etc.) |

---

## Auth

### Signup — two steps, email-verified

Registration requires proof that the applicant controls the address.
`POST /user/signup` **does not create an account**; it stages the
credentials in `pending_signup` and mails a 6-digit code. The account
exists only once `POST /user/verify-signup-otp` succeeds. There is no
other code path that writes a `user` row (technicians excepted — those
are created by an already-authenticated owner via
`/user/create-technician`).

#### `POST /user/signup` — step 1

Email must be unique (409 if taken) and the password 8–128 characters
with no leading/trailing whitespace. The password is Argon2id-hashed on
arrival and is never stored in the clear, not even while pending.

**Body**
```json
{
  "user_email": "owner@example.com",
  "input_password": "Secret123!",
  "device_id": "a1B2c3"
}
```
`device_id` is optional, 6 alphanumeric characters.

**Real HTTP 200** (body `status_code: 200`)
```json
{ "status_code": 200,
  "message": "A verification code has been sent to owner@example.com. Enter it to finish creating your account.",
  "data": { "email_sent": true, "user_email": "owner@example.com",
            "expires_in_minutes": 15,
            "message": "A verification code has been sent to owner@example.com. Enter it to finish creating your account." } }
```

| Status | When |
|---|---|
| 409 | that email already has an account, or an `IntegrityError` race between two concurrent step-1 calls for the same email |
| 422 | password under 8 / over 128 chars, malformed email, etc. |
| 429 | another code was requested under `SIGNUP_OTP_RESEND_COOLDOWN_SECONDS` (60s) ago, `SIGNUP_OTP_MAX_SENDS` (5) codes already sent for this signup, or the caller is over `SIGNUP_RATE_LIMIT_PER_EMAIL` (15 / 900s, **per-email, not per-IP**) — all three set `Retry-After` |
| 500 | DB error staging the signup, or mail send failure (the staged row is discarded, not left dangling) |

#### `POST /user/verify-signup-otp` — step 2 (creates the account)

**Body**
```json
{ "user_email": "owner@example.com", "otp_code": "482913", "device_id": "a1B2c3" }
```

**Real HTTP 200** (body `status_code: 201`)
```json
{ "status_code": 201, "message": "Email verified — account created successfully",
  "data": { "user_id": 1, "email": "owner@example.com", "role": "OWNER" } }
```

The staged signup is deleted in the same transaction that creates the
user, so the code cannot be replayed. A wrong code returns `400` naming
the attempts remaining; after `SIGNUP_OTP_MAX_ATTEMPTS` (5) failures — or
once the code expires (`SIGNUP_OTP_TTL_SECONDS`, 15 min) — the staged
signup is discarded and signup must be started again (`404` on the next
attempt). `409` if the email became taken between step 1 and step 2. New
accounts default to role `OWNER`.

#### `POST /user/resend-signup-otp`

**Body**: `{ "user_email": "owner@example.com" }` — mails a fresh code for
a signup already in flight and invalidates the previous one immediately.
The password is not resubmitted, so a resend cannot change it. `404` if
nothing is pending for that address (also opportunistically purges an
expired staged row if one is found); `429` while inside the cooldown, over
`SIGNUP_OTP_MAX_SENDS`, or over the per-email rate limit.

### `POST /user/login`

**Body**
```json
{ "user_email": "owner@example.com", "input_password": "Secret123!",
  "device_id": "a1B2c3", "source": null, "source_platform": null }
```

**200**
```json
{ "status_code": 200, "message": "Login successful",
  "data": { "access_token": "eyJ...", "user_id": 1, "email": "owner@example.com", "role": "OWNER",
            "refresh_token": "eyJ...", "device_id": "a1B2c3" } }
```

Also sets the `refresh_token` httpOnly cookie (**`Secure` is not set on
this cookie** — `samesite="lax"`, not `secure=True`; keep this in mind
behind HTTPS-only deployments). Access token expiry is
`ACCESS_TOKEN_EXPIRE_MINUTES`; refresh via `/user/renew-access-token`.
`400 "Invalid email or password"` on unknown email or an Argon2 mismatch
— deliberately generic, does not distinguish the two.

### `POST /app/login`

Identical body/behavior to `/user/login`, but the response additionally
includes `password_hash` (the raw Argon2id PHC string) for offline mobile
verification. Treat this endpoint as more sensitive than `/user/login`.

### `GET /user/renew-access-token`

Reads the `refresh_token` httpOnly cookie and returns a fresh access
token. No body, no bearer required. Does **not** rotate the refresh
cookie — only a new access token is issued.

**200** `{ "data": { "access_token": "eyJ..." } }`

`401` for a missing cookie ("No refresh token found"), an expired/invalid
refresh token, or a user that no longer exists.

### `POST /user/logout`

Bearer, any role. Sets `User.IsLogout = 1`. **Does not revoke refresh
tokens** — a still-valid refresh cookie can mint new access tokens after
logout (compare with `/user/reset-password`, which does revoke).

### Password reset — three steps, enumeration-safe

#### `POST /user/forgot-password`

**Body**: `{ "user_email": "owner@example.com" }`. Always returns
**200** with the same generic body regardless of whether the email
exists or is active — this is a deliberate choice (see
`docs/signup-otp-enumeration-choice.md`-style reasoning): don't leak
account existence via this endpoint. OTP purpose `PASSWORD_RESET`, TTL
`PASSWORD_RESET_OTP_TTL_SECONDS` (15 min), max `OTP_MAX_ATTEMPTS` (5).
Issuing a new code invalidates the previous live one for that
`(user, purpose)` scope.

```json
{ "status_code": 200, "message": "...",
  "data": { "email_sent": true,
            "message": "If an account exists for that email address, a verification code has been sent to it." } }
```

#### `POST /user/verify-reset-otp`

**Body**: `{ "user_email": "owner@example.com", "otp_code": "482913" }`
**200**: `{ "data": { "reset_token": "eyJ...", "expires_in_minutes": 15 } }`

`reset_token` is a short-lived JWT (`PASSWORD_RESET_TOKEN_EXPIRE_MINUTES`,
15 min) whose payload embeds a 16-char fingerprint of the user's *current*
password hash — this is what makes the token single-use (see below).
`404` if the email is unknown/inactive or no live OTP exists (same
wording either way); `400` for an expired code or too many wrong
attempts.

#### `POST /user/reset-password`

**Body**: `{ "reset_token": "eyJ...", "new_password": "NewSecret123!" }`
(8–128 chars, same rule as signup).

**200**: `{ "data": { "user_id": 1, "email": "...",
"message": "Password reset successfully. Please log in with your new
password." } }`

Revokes **every** `RefreshToken` row for the user and sets
`IsLogout = 1` — this logs the user out everywhere, unlike `/user/logout`.

| Status | When |
|---|---|
| 400 | reset session expired; invalid/wrong-purpose token; **token already spent** (the embedded password-hash fingerprint no longer matches — i.e. the token was already used to change the password once); new password same as current |
| 404 | account not found or deactivated |

### `POST /user/impersonate` — ADMIN only

**Body**: `{ "user_id": 42, "medical_store_id": 7 }` (`medical_store_id`
optional — required only if you want the impersonation token scoped to a
specific store the target owns).

**200**: same shape as login's `data`, plus `pharmacy_id`. Token expires
in 60 minutes (longer than a normal access token); **no refresh cookie is
issued** for an impersonation session.

`403` if caller isn't ADMIN; `404` for an unknown target user or an
unknown `medical_store_id`; `400` if the given store doesn't belong to
the target user.

---

## User

### `POST /user/create-technician`

Owners create techs for stores they own; admins can create anywhere;
technicians are forbidden.

**Body**
```json
{
  "user_name": "tech1",
  "user_email": "tech1@example.com",
  "contact": "9999999999",
  "input_password": "TechSecret!",
  "medical_store_id": 1,
  "device_id": "a1B2c3"
}
```
Note: unlike signup, this schema has **no minimum-length validator on
`input_password`** — whatever string is supplied is Argon2-hashed as-is.

### `POST /user/get-technician`

Despite being a read/list operation this is a **POST**, with `ph_id` as
an optional **query** parameter (not a body). Owners see technicians of
their own stores only (omitting `ph_id` returns technicians across *all*
owned stores); admins see all, optionally filtered; `403` for technicians
and for an owner passing a `ph_id` they don't own.

### `GET /user/me`, `PUT /user/update/me`, `DELETE /user/delete/me`

Self-serve profile. `update` body is a partial (`exclude_unset`):

```json
{ "name": "New Name", "user_email": "new@example.com", "phone": "8888888888", "device_id": null }
```
Note: this endpoint does **not** validate email uniqueness/format at the
route level — a duplicate email would surface as a raw, uncaught
`IntegrityError` → `500`, not a clean `409` (unlike the signup/create
paths, which catch it). `delete` is a **soft delete** (`IsDeleted = True`
only — the row is not removed).

### `PUT /user/update/{user_id}`, `DELETE /user/delete/{user_id}`

Admin can target anyone. Owner can target self or technicians belonging
to their own pharmacy (`403 "This technician does not belong to your
pharmacy"` / `"You can only update yourself or your own technicians"`).
Technicians must use `/me` instead (`403 "Use /user/update/me to update
your own profile"`). Both are soft deletes / partial updates.

### `GET /user/all`, `/user/by-email?user_email=...`, `/user/by-role?role=OWNER`

Admin-only listing/search endpoints. `403` for other roles. `by-role`
does **not** validate that `role` is one of `OWNER`/`TECHNICIAN`/`ADMIN`
— an unrecognized string just yields an empty list rather than a 422.

---

## Pharmacy / medical store

### `POST /pharmacy/create-pharmacy`

```json
{ "pharmacy_title": "My Store", "pharmacy_location": "Brooklyn NY 11226",
  "city": null, "state": null, "zip_code": null, "store_code": null, "device_id": null }
```

The pharmacy is **always** owned by the caller (`user.user_id`) — there
is no way to create a store on behalf of someone else through this
endpoint, even as ADMIN. **Real HTTP 200** (body `status_code: 201`)
returns `{ data: { pharmacy_id, name, address, city, state, zip_code,
store_code, owner: { user_id, email, role } } }`.

### `GET /pharmacy/get-pharmacy?ph_id=`

- Admin → all stores (optionally filtered by `ph_id`), with `owner` populated.
- Owner → own stores; `owner` field is nulled out for privacy.
- Technician → `403`.

### `GET /pharmacy/get-pharmacy-by-owner?owner_id=`

ADMIN only. Returns every store owned by `owner_id`.

### `GET /pharmacy/by-name?name=Deva`

Case-insensitive partial (`ILIKE %name%`) match. Owner sees only own
stores.

### `PUT /pharmacy/update/{ph_id}`

Partial body: `{ pharmacy_title, pharmacy_location, city, state,
zip_code, store_code, device_id }` (all optional).

### `DELETE /pharmacy/delete/{ph_id}`

**Soft delete** (`IsDeleted = True`) — despite the intuitive expectation
of a hard delete, the pharmacy row and its related data are **not**
actually removed; there is no FK-cascade wipe on this path.

---

## Pharmacy ownership transfer

Two-OTP handshake so a pharmacy changes hands only with both parties'
active consent — the current owner confirms *their own* identity first,
then the recipient confirms theirs. State machine
(`core/enums.py::OwnershipTransferStatus`): `PENDING → ACCEPTED |
REJECTED | CANCELLED`, or lazily `PENDING → EXPIRED` once
`TRANSFER_REQUEST_TTL_HOURS` (48h) elapses — there's no background
sweeper, expiry is applied on every read/mutate.

### `POST /pharmacy/ownership-transfer/initiate` — OWNER only

```json
{ "medical_store_id": 1, "new_owner_email": "newowner@example.com",
  "new_owner_id": null, "message": "Retiring, handing off to you." }
```
Supply `new_owner_email` **or** `new_owner_id` (not both required). Mails
an OTP (purpose `TRANSFER_CREATE`) **to the current owner's own address**
— a self-verification step before the transfer request even exists.

| Status | When |
|---|---|
| 400 | neither email nor id given; new owner is the caller; recipient is deactivated; recipient isn't a `PHARMACY_OWNER`-role account |
| 404 | pharmacy not found; no Queue RX account for that email/id |
| 403 | caller doesn't own the pharmacy |
| 409 | a `PENDING` transfer already exists for this pharmacy |

### `POST /pharmacy/ownership-transfer/create` — OWNER only

Same body as `/initiate` plus `otp_code`. Creates the `PENDING` row
(`expires_at = now + 48h`) and emails the **recipient** (best-effort —
mail failure doesn't roll back the already-committed request). **Real
HTTP 200** (body `status_code: 201`).

### `GET .../outgoing`, `GET .../incoming`, `GET .../my`

`outgoing` = requests where you're `current_owner_id` (`pending_only`
defaults **false**). `incoming` = requests where you're `new_owner_id`
(`pending_only` defaults **true** — the poll target for "someone wants to
make you owner"). `my` returns `{ incoming, outgoing,
pending_incoming_count }` in one call. All flip stale `PENDING` rows to
`EXPIRED` on read.

### `POST .../{id}/send-otp` — must be the named recipient

Mails an OTP (purpose `TRANSFER_ACCEPT`) to the recipient, scoped to
`(medical_store_id, transfer_id, new_owner_id)`. `400` if the transfer is
no longer `PENDING`.

### `POST .../{id}/accept` — must be the named recipient

Body: `{ "otp_code": "482913" }`. Flips `Pharmacy.user_id` to the new
owner in the same transaction as marking the transfer `ACCEPTED`.
`409 "This pharmacy has already changed ownership"` if the pharmacy's
current owner no longer matches the transfer's recorded
`current_owner_id` (e.g. a race with another transfer) — the stale
transfer is auto-cancelled as a side effect of that check. Previous owner
is emailed the outcome (best-effort).

### `POST .../{id}/reject` — must be the named recipient

Body optional: `{ "reason": "Not interested" }`. No OTP required.

### `POST .../{id}/cancel` — current owner or ADMIN

Withdraws a still-`PENDING` request.

### `GET .../{id}` — either party or ADMIN

Detail view; flips stale `PENDING → EXPIRED` on read.

---

## Subscriptions & plan gating

Feature entitlement lives on `Plan.features` (a DB JSON list of
`Feature` enum string values, admin-editable at runtime — not hardcoded
per-tier in code) and `Plan.limits` (a DB JSON dict of soft caps, e.g.
`{"drug_reconciliation_limit": 250}`; an absent key means unlimited).
Three tiers (`core/enums.py::PlanCode`): `BASIC` ($29/mo) → `ADVANCED`
($179/mo) → `ULTIMATE` ($349/mo), additive — every feature below a tier
is included at that tier and above.

| Feature flag | Min plan | Gates |
|---|---|---|
| `inventory_lite` | Basic | `/pharmacy/{ph_id}/inventory*`, barcode processing, filters `GET /documents/` |
| `invoice_upload_manual`, `compliance_reports`, `expiration_lot_tracking`, `overstock_monitoring`, `multi_location_access`, `temp_monitoring_alerts` | Basic | — (`compliance_reports` gates `/activity` and `/audit-report`) |
| `invoice_to_inventory_auto` | Advanced | `POST /invoices`, `GET /invoices*`, invoice document processing |
| `top_quantity_drug_report` | Advanced | all of `/dispenses*`, `/reports/*`, dispense document processing (also gates Module G in the validation engine) |
| `pack_size_billed_reconciliation` | Advanced | Module C in the validation engine |
| `refill_analysis_billings` | Advanced | `/pharmacy/{ph_id}/refills*` (also gates Modules E/F/H) |
| `insurance_ndc_analytics`, `custom_patient_med_reports` | Advanced | — (reserved; not wired to any route or validation module yet) |
| `invoice_billed_cross_reconciliation` | Ultimate | `/pharmacy/{ph_id}/reconciliation/invoice-vs-billed` |
| `days_supply_validation`, `discontinued_drug_detection`, `ndc_claim_mismatch_checks` | Ultimate | Modules D/A/B in the validation engine |
| `annual_checkup_audit`, `early_access_features` | Ultimate | — (reserved) |

**Two independent gates stack on the dispense-validation routes**: the
whole endpoint (`/dispenses/validate`, `/dispenses`, etc.) is gated
behind `top_quantity_drug_report` (Advanced) via `ensure_feature` *before*
validation ever runs; only once that clears does the validation engine's
own per-module `granted` set (built from the same `Plan.features`)
decide which of A–H actually execute. A Basic-plan store gets a flat
`402` and never sees a `PLAN_LOCKED` alert for modules it might otherwise
qualify for.

### `GET /plans`

Bearer, any role. Lists all `is_active=True` plans.

### `GET /subscription/{ph_id}`

`404 "This pharmacy has no subscription"` if none exists.
`SubscriptionOut`: `{ subscription_id, pharmacy_id, plan_id, plan,
status, started_at, current_period_end, cancelled_at, notes,
stripe_subscription_id }`.

An `ACTIVE` subscription whose `current_period_end` has passed is
**lazily flipped to `EXPIRED`** the next time it's read (in
`get_active_subscription`, called by `ensure_feature`) — there's no
cron/sweeper; a store can look ACTIVE in a stale cache until the next
gated call touches it.

### `POST /subscription/subscribe` — OWNER/ADMIN

```json
{ "medical_store_id": 1, "plan_code": "ADVANCED" }
```
Creates a Stripe Checkout Session; **the DB subscription row is not
created here** — activation happens asynchronously via the
`checkout.session.completed` webhook. `409` if the store already has an
active subscription (use upgrade instead). **Real HTTP 200** (body
`status_code: 201`). `data.session_id` is currently a hardcoded empty
string — only `checkout_url` is populated; don't rely on `session_id`
from this response.

### `PUT /subscription/upgrade` — OWNER/ADMIN

```json
{ "medical_store_id": 1, "plan_code": "ULTIMATE" }
```
`400 "Cannot upgrade legacy subscriptions via Stripe. Please cancel and
re-subscribe."` if the record has no `stripe_subscription_id` (i.e. it
was admin-assigned, not Stripe-originated). Stripe applies the change
with `proration_behavior="always_invoice"`. **The returned
`SubscriptionOut` reflects the OLD plan** — the DB is only updated later
by the `customer.subscription.updated` webhook, so don't trust this
response body for the new plan; poll `GET /subscription/{ph_id}` after a
beat, or listen for the webhook side effect.

### `POST /subscription/cancel` — OWNER/ADMIN

```json
{ "medical_store_id": 1, "cancel_immediately": false }
```
Two paths: a **legacy** subscription (no `stripe_subscription_id`)
cancels synchronously in the DB. A **Stripe-backed** one calls Stripe
(immediate or `cancel_at_period_end`) and returns the **stale** `sub`
object (still `ACTIVE`) — the real DB flip happens via the
`customer.subscription.deleted`/`.updated` webhook.

### `GET /subscription/{ph_id}/payments?skip=0&limit=50`

`{ data: { payments: [...], total } }`. No upper bound is enforced on
`limit` client-side.

### Admin subscription management (`/admin/*`, ADMIN only)

`GET /admin/subscriptions?status=&plan_id=&medical_store_id=` — `status`
is an **unvalidated free string**, not checked against the enum.

`POST /admin/subscriptions` and `PUT /admin/subscriptions/{id}` **bypass
Stripe entirely** — direct DB upsert/edit. Useful for comping an account
or fixing a stuck record, but can create a subscription with no
corresponding Stripe object, which will diverge silently if that store
later hits a Stripe-driven code path. Both real HTTP 200 despite body
`status_code: 201` on the POST.

`POST /admin/subscriptions/{id}/revoke` — immediate cutoff
(`current_period_end = now`, no grace), calls Stripe to cancel
immediately if `stripe_subscription_id` is set.

`POST /admin/plans` / `PUT /admin/plans/{id}` — `422 "Unknown feature
key(s): ..."` if any string in `features` isn't a real `Feature` enum
value. `code` is immutable after creation (no `code` field on the update
schema). `409` on `POST` if the `code` already exists.

---

## Stripe webhooks

### `POST /webhooks/stripe`

**No bearer auth** — verified via the `stripe-signature` header against
`STRIPE_WEBHOOK_SECRET`. Returns a raw (non-enveloped) `{"status":
"success", "message": "Event received and queued for background
processing"}` on `200`.

**Important**: signature verification is synchronous, but the actual
event handling runs in a FastAPI `BackgroundTask` *after* the `200` is
already sent. A handler exception is only logged
(`logger.exception`) — it is **never surfaced to Stripe**, so Stripe will
not retry it (its webhook already got a 200). If a subscription looks
stuck, check the app logs for a background-task exception before
assuming Stripe didn't deliver the event.

| Status | When |
|---|---|
| 400 | missing `stripe-signature` header; invalid payload; invalid signature (including a misconfigured/empty `STRIPE_WEBHOOK_SECRET` — only logged, not pre-checked) |

Handled event types: `checkout.session.completed` (activates/creates the
subscription), `invoice.paid` (extends `current_period_end`, logs a
payment), `invoice.payment_failed` (logs a failed payment),
`customer.subscription.deleted` (cancels), `customer.subscription.updated`
(syncs period/status, detects plan changes via `stripe_price_id`). Any
other event type is logged at debug and ignored — still `200`.

---

## Documents — extraction pipeline

### `POST /documents/process`

The only upload endpoint. Sends file(s) through the Kafka pipeline, which
extracts structured JSON and returns it inline. **No domain rows in
`invoices` / `drug_reports` are created here.** Save flow happens via
`POST /invoices` and `POST /dispenses`.

**Form fields** (multipart):

| Field | Type | Notes |
|---|---|---|
| `process_type` | enum | `invoice` / `dispense` / `barcode` |
| `medical_store_id` | int | required; ownership- and feature-checked |
| `files` | List[file] | **exactly 1** for `invoice`/`dispense`; **1 or 2** for `barcode` (barcode + datamatrix can be in separate images) |

Feature gate per `process_type`: `invoice → invoice_to_inventory_auto`,
`dispense → top_quantity_drug_report`, `barcode → inventory_lite`.

**File extension restrictions** (`core.enums.ALLOWED_EXTENSIONS`):

| process_type | allowed |
|---|---|
| `invoice` | `pdf` |
| `dispense` | `pdf`, `docx`, `doc`, `xlsx`, `xls` |
| `barcode` | `png`, `jpg`, `jpeg`, `heic`, `heif` |

Flow: `ensure_pharmacy_access` → `ensure_feature` → file-count check →
every file is fully read/validated (extension, non-empty, ≤
`DOCUMENT_MAX_FILE_SIZE_MB` = 50 MB) **before** any DB row is created →
file(s) stored to disk (`doc_key = uuid4().hex`, second barcode image at
key `{doc_key}-2`) → `Document` row inserted at `QUEUED` → **a
`result_bus.register(doc_key)` future is created before the Kafka publish
call**, so the worker's broadcast result can never race ahead of
registration → job published → `await asyncio.wait_for(future,
PROCESSING_RESULT_TIMEOUT_SECONDS)` (**180s**).

**200 happy path** (`data` shape depends on `process_type`):
```json
{
  "doc_key": "7d902...",
  "process_type": "dispense",
  "status": "COMPLETED",
  "message": "Document processed successfully.",
  "data": {
    /* dispense: pharmacy/medicines/grand_total + a Tier-1-only validation block.
       invoice: seller/customer/line_items/summary.
       barcode: {matched: [...], unmatched: [...]}. */
  }
}
```

**Timeout** (still real HTTP 200 — see the Conventions note on envelope
vs. real status): if processing exceeds 180s, the response body carries
`status: "QUEUED"`, `data: null` — poll `GET /documents/{doc_key}` until
status flips to `COMPLETED` / `FAILED_PERMANENTLY`. If the API process is
shutting down mid-wait, a real `503` is raised instead.

If the extraction itself terminally fails (all retries exhausted), the
response is still real HTTP 200 with `status: "FAILED_PERMANENTLY"` and
an `error` field — this is a *logical* failure, not an HTTP error, since
the upload itself succeeded.

**Common errors**:

| Status | Cause |
|---|---|
| 400 | wrong file count for the process_type, unsupported extension, empty file |
| 402 | `ensure_feature` — no active subscription, or plan lacks the flag for this `process_type` |
| 403 | `medical_store_id` not accessible to caller |
| 413 | file size > `DOCUMENT_MAX_FILE_SIZE_MB` (50 MB) |
| 500 | disk storage failure, or DB commit failure creating the `Document` row (stored file(s) are cleaned up in this case) |
| 503 | Kafka broker unreachable at publish time, or server shutdown mid-await |

### `GET /documents/{doc_key}`

Returns the `documents` row including the JSON-stringified `result_data`.
`404` if `doc_key` unknown; `403` via `ensure_pharmacy_access`; `402` via
`ensure_feature` for the document's own `process_type`.

### `GET /documents/?skip=0&limit=50`

Paginated list, `Document.created_at DESC`. ADMIN sees all. Owner/
Technician see their store(s)' documents **and only for stores entitled
to `inventory_lite`** — a non-entitled technician's store yields an
empty page rather than a 402 (list endpoints filter silently; only the
single-doc `GET` and the upload route raise 402).

---

## Invoices

Reads live in `routes/invoice.py`; the persist endpoint lives in
`routes/invoice_save.py` — both are mounted under `/invoices`.

### `POST /invoices`

Strict schema (`schemas/save_invoice.py`, `extra="forbid"` at every
nesting level). Body shape matches the `data` block returned by
`/documents/process?process_type=invoice` — you can pipe `data → body`
with no transformation, and the same endpoint is used whether the JSON
originated from a document upload or was typed by hand in the UI (there
is no separate "manual invoice" endpoint — `schemas/manual_invoice_input.py`
exists in the codebase but is **not wired to any route**; ignore it).

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
      "raw_ndc": "72888000901", "ndc": "72888000901",
      "ndc11": "72888000901", "upc": null,
      "lot_number": "2097749781",
      "invoiced_qty": "1", "order_qty": "1", "uom": "ea",
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

NDC resolution per line item (`_resolve_ndc_fields`): if the caller
explicitly supplies `ndc11` or `upc`, those are trusted verbatim; if
neither is present, the raw extractor `ndc` field is auto-classified.
`verified` defaults to `false` if omitted.

**Real HTTP 201**
```json
{
  "invoice_id": 1,
  "pharmacy_id": 1,
  "line_items_created": 5,
  "summary_saved": true,
  "inventory_updates": [
    { "code": "72888000901", "delta": "1", "new_quantity": "1" }
  ]
}
```

`inventory_updates` echoes the `medicine_inventory` rows that were
incremented (or created). `code` is `ndc11` if present, else the
digits-only `upc`. Quantity applied per line is `invoiced_qty` (falling
back to `order_qty` if blank); a line with neither a resolvable code nor
a parseable quantity is silently skipped. `exp_date` on the inventory row
is only overwritten when the line carries a scanned `dm_expiration_date`
(a plain re-buy invoice never wipes a previously known expiry).

`422`: schema violation (unknown field anywhere in the tree — every
nested model is `extra="forbid"`). `403`: ownership check failed. `402`:
`ensure_feature(invoice_to_inventory_auto)`.

### `GET /invoices/?skip=0&limit=50`

List, store-scoped (filtered through `entitled_store_ids` for
non-admins), `Invoice.id DESC`.

### `GET /invoices/{invoice_id}`

Detail with `line_items[]` and `summary` populated. `404` if not found.

---

## Dispenses & validation engine

Reads/validate live in `routes/dispense_validate.py`; persist/patch live
in `routes/dispense_save.py`. See `docs/validation_engine.md` for the
full module catalogue — this section covers only the HTTP surface.

### `POST /dispenses/validate`

Body identical to `POST /dispenses` (`DispenseSaveRequest`). Runs
**Tier 1 + Tier 2** (every module the store's plan grants) and returns a
`ValidationReport`. **No DB writes.** Used by the UI for live feedback
after each form edit.

**Response**
```json
{
  "summary": { "errors": 1, "warnings": 3, "info": 12, "indeterminate": 0,
               "blocking": true, "tier1_ran": true, "tier2_ran": true },
  "alerts": [
    { "module": "C", "code": "UNIT_OF_USE_FRACTIONAL", "severity": "ERROR",
      "medicine_index": 5, "dispense_index": 0, "ndc": "00310461612",
      "rx_no": "504850.0", "field": "qty_disp", "actual": "32.1",
      "suggestion": null }
  ],
  "grand_total": { "printed_rx_count": 99, "recomputed_rx_count": 98, "..." : "..." },
  "per_patient": [ { "patient_key": "16a955...", "patient_label": "ESPOSITO, F.",
                      "rx_count": 1, "total_price": "4471.68", "..." : "..." } ]
}
```

First call against a set of not-yet-cached NDCs costs ~1–2s per NDC
(FDA HTTP, on a fresh worklist that can add up to ~30-60s for a large
report); cached calls (within `NDC_CACHE_TTL_DAYS`, default 7) are
sub-second. `402` via `ensure_feature(top_quantity_drug_report)` —
Advanced tier or above only, independent of which individual modules
(A–H) the plan grants beneath that.

### `POST /dispenses`

Same body, plus an optional `force_save: bool = false`. **Always
re-validates from scratch** — an `validation` block echoed back from a
prior `/documents/process` call in the request body is accepted but
ignored.

If `validation.summary.blocking` (any `ERROR`-severity alert) is true and
`force_save` is false → **422** with the full `ValidationReport` in
`detail.data`, nothing written:
```json
{ "detail": {
    "status_code": 422,
    "message": "Dispense save blocked by 4 validation error(s). Fix the listed issues and resubmit, or set `force_save: true` to persist anyway.",
    "data": { "...": "full ValidationReport" }
} }
```

If `force_save: true` and blocking errors are present, the save proceeds
anyway: the report is flagged `force_saved=True`, and the `ERROR`-severity
alerts are stamped onto `DrugReport.validation_errors` (report-level) and
onto each affected `Medicine.validation_errors`/`has_errors` (grouped by
`medicine_index`) for later audit (`GET /pharmacy/{ph_id}/audit-report`
surfaces exactly these force-saved rows).

Before persisting, a **duplicate `rx_no` guard** runs: if any incoming
`rx_no` already exists among this pharmacy's non-deleted `Dispense` rows,
the whole save is rejected with **409**, regardless of validation
severity or `force_save`:
```json
{ "detail": {
    "status_code": 409,
    "message": "Duplicate document: 3 rx_no(s) already exist for this pharmacy. Duplicate rx_no: [...]",
    "data": { "duplicate_rx_nos": [...] }
} }
```

On success:
1. Inserts `DrugReport` + N `Medicine` + M `Dispense` rows.
2. Calls `subtract_dispense_quantities`: per medicine, `−sum(qty_disp)`
   upsert into `medicine_inventory`.
3. Returns `DispenseSaveResponse` (validation block still attached,
   showing whatever non-blocking WARNING/INFO/INDETERMINATE alerts
   remain).

**Body** (representative)
```json
{
  "medical_store_id": 1,
  "document_id": 1,
  "force_save": false,
  "pharmacy": {
    "pharmacy_name": "Good Health Pharmacy",
    "address": "1379-83 Nostrand Ave, Brooklyn, NY 11226",
    "phone": "(718)618-7425", "fax": "(718)618-7428",
    "report_date": "2/1/2026",
    "report_from_date": "1/30/2026", "report_to_date": "2/1/2026"
  },
  "grand_total": { "total_price": "29832.03", "total_rx_count": "99", "total_cost": "45579.93" },
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
Manual entry, exactly as with invoices, uses this same schema by hand —
`schemas/manual_dispense_input.py` exists but is **not wired to any
route**; ignore it.

**Real HTTP 201**
```json
{
  "report_id": 1,
  "pharmacy_id": 1,
  "medicines_saved": 86,
  "dispenses_saved": 98,
  "force_saved": false,
  "medicines_with_errors": 0,
  "inventory_updates": [ { "code": "76204020025", "delta": "-75.000", "new_quantity": "-75.000" } ],
  "validation": { "...": "same shape as /validate" }
}
```

Note: the drug-count quota (`Plan.limits.drug_reconciliation_limit`, 250
for Basic/Advanced, unlimited for Ultimate) is **currently disabled on
this route at launch** — a report with more than 250 distinct medicines
will still save via `POST /dispenses`. It **is** enforced on `PUT
/dispenses/{report_id}` (see below).

### `PUT /dispenses/{report_id}` — full replace

Same body/validation/force_save semantics as `POST /dispenses`, but:
- `404 "Dispense report not found"` if `(report_id, medical_store_id)`
  doesn't match an existing row.
- **The 250-drug quota IS enforced here**: `402` with `"Your plan allows
  up to {cap} drugs reconciled per report; this report has {n}. Upgrade
  to Ultimate for unlimited."` if exceeded.
- No duplicate-`rx_no` guard (you're replacing the same report, so its
  own prior `rx_no`s are expected to reappear).
- Reverses the report's old inventory impact, deletes all its existing
  `Medicine` rows (cascades to `Dispense`), rewrites `DrugReport`
  metadata, re-inserts everything from the body, then reapplies the new
  inventory impact.

### `PATCH /dispenses` — partial patch by `rx_no`

Targeted field-level correction without re-submitting the whole report.
**The validation engine is not invoked on this route** — no Tier-1/Tier-2
run, no blocking behavior; this is a trusted, surgical edit path.

```json
{
  "medical_store_id": 1,
  "dispenses": [
    { "rx_no": "507979", "qty_disp": "90.000", "days_supply": 6 }
  ]
}
```
Only non-null fields in each patch line are applied
(`exclude_unset`-style). For each patched line: the old inventory impact
is reversed, the new field values are applied, the new inventory impact
is subtracted, and the parent `Medicine`/`DrugReport` totals are
recalculated. `404` with `{"missing_rx_nos": [...]}` if any `rx_no` isn't
found for the pharmacy.

**200**: `{ "medical_store_id": 1, "dispenses_patched": 1,
"inventory_updates": [ {...} ] }`

### `PATCH /dispenses/document` — patch via a re-uploaded corrected document

Multipart: `medical_store_id` (Form int), `force_save` (Form bool,
default false), `file` (the corrected PDF/Excel). Extraction here runs
**synchronously** via `services.document_extractor` (in a thread), **not**
through the Kafka pipeline — this is a direct, blocking extraction call,
not `/documents/process`.

Flow: extract → collect the document's `rx_no`s (`400 "No rx_no values
found in the provided document."` if none) → find which already exist
for this pharmacy (`404 "None of the rx_no values in the document exist
in the database for this pharmacy."` if none match) → filter the
extracted report down to only the matched `rx_no`s → run Tier1+Tier2 on
**only that filtered subset** → same 422-blocking/`force_save` behavior
as `POST`/`PUT` → patch each matched dispense the same way as the plain
`PATCH /dispenses` route.

**200**: `DispenseSaveResponse`, with `report_id` = the first touched
report's id (0 if none touched), `medicines_saved`/`dispenses_saved`
scoped to the filtered subset actually patched.

---

## Drug reports (read-side)

### `GET /reports/?skip=0&limit=50`

Lightweight list — owner/tech sees their stores (filtered through
`entitled_store_ids`), admin sees all. `DrugReport.id DESC`.

### `GET /reports/{report_id}`

Full report: `DrugReport` + `medicines[]` + each `medicine.dispenses[]`.
All eager-loaded via `lazy="selectin"`. `404 "Report {id} not found."`

### `GET /reports/{report_id}/medicines/{ndc}`

One medicine in the context of one report. `404` for either an unknown
report or an NDC not present in it.

### `DELETE /reports/{report_id}`

**Soft delete** (`IsDeleted = True`) — does not cascade-delete
`Medicine`/`Dispense` rows and does **not** reverse the earlier inventory
subtraction (no automatic call to `reverse_dispense_quantities`); treat
as a manual data-fix operation, not a true undo.

---

## Inventory

### `GET /pharmacy/{ph_id}/inventory?q=&only_negative=&skip=0&limit=50`

`limit` is bounded `1..500` at the schema level.

```json
{
  "pharmacy_id": 1,
  "items": [
    { "code": "72888000901", "product_name": "BACLOFEN TB 5MG 100",
      "quantity": "-30.000", "status": "Out of stock", "location": null,
      "exp_date": null, "last_invoice_id": 1, "updated_at": "2026-06-13T12:00:00" }
  ],
  "total": 12, "skip": 0, "limit": 50
}
```
`status` is derived (`derive_stock_status`): `quantity <= 0` → `"Out of
stock"`; `quantity <= 10` → `"Low stock"`; else `"In stock"`. Negative
`quantity` = dispensed without a matching invoice (UI shows "missing
invoice" warning). Sorted by `code`.

### `GET /pharmacy/{ph_id}/inventory/{code}`

Single-row detail, adds `manufacturer` (from the NDC cache's
`brand_name`), `dosage_form`, `lot_number` (latest invoice line item),
`last_added`. `404 "No inventory row for code '{code}'"`.

### `PATCH /pharmacy/{ph_id}/inventory/{code}` — OWNER/ADMIN only

```json
{ "quantity": "42.000", "product_name": null, "exp_date": null, "location": "Aisle 3" }
```
**`quantity` is an absolute correction (a SET), not a delta** — unlike
the `+`/`−` deltas invoice-save and dispense-save apply. `403 "Only
owners can adjust inventory"` for technicians. `422 "Invalid quantity
'{value}'"` for a non-numeric string. `404` for an unknown code. Logs an
`INVENTORY_ADJUSTED` activity row with the before/after diff when
anything actually changed.

---

## Reconciliation — invoice vs. billed (Ultimate only)

### `GET /pharmacy/{ph_id}/reconciliation/invoice-vs-billed?only_mismatch=false`

Compares, per NDC, quantity **purchased** (summed from `InvoiceLineItem`,
keyed on `ndc11`) against quantity **billed out** (summed from
`Dispense` via `Medicine.ndc`). Not pack-size normalized — invoice qty
may be in packages while dispensed qty is in units (that's a separate
check, `pack_size_billed_reconciliation` → Module C in the validation
engine).

```json
{
  "pharmacy_id": 1,
  "summary": { "ndc_count": 40, "over_billed": 3, "under_dispensed": 5, "matched": 32 },
  "items": [
    { "ndc": "76204020025", "drug_name": "ALBUTEROL SULFATE 0.083% SOL",
      "invoiced_qty": "100.000", "dispensed_qty": "112.000",
      "delta": "12.000", "status": "OVER_BILLED" }
  ]
}
```
`status`: `dispensed > invoiced` → `OVER_BILLED`; `invoiced > dispensed`
→ `UNDER_DISPENSED`; else `MATCHED`. `only_mismatch=true` drops
`MATCHED` rows from `items` (but `summary.matched` still counts them).
Sorted `OVER_BILLED` first, then by descending `|delta|`. `402` via
`ensure_feature(invoice_billed_cross_reconciliation)`.

---

## Refills worklist (Advanced+)

### `GET /pharmacy/{ph_id}/refills?status=&medicine=&customer=&due_within_days=`

Surfaces patients whose next refill is due soon or overdue, derived from
the most recent dispense per `(patient_key, ndc)` pair
(`services/refill_service.py`). `next_due = date_filled + days_supply`;
`status` thresholds (`_DUE_SOON_DAYS = 7`): no computable `next_due` →
`"UNKNOWN"`; `days_remaining < 0` → `"OVERDUE"`; `0–7` → `"DUE_SOON"`;
`> 7` → `"OK"`. Sorted most-urgent first (`UNKNOWN` last). Not
paginated — returns the full filtered list. Excludes any
`(patient_key[, ndc])` pair present in `refill_dismissals` for the store.

```json
{
  "pharmacy_id": 1,
  "items": [
    { "patient_key": "2f7d994fb191d02d", "customer_name": "DUPONT HERARD, MARIE",
      "phone": "3478585259", "drug_name": "ALBUTEROL SULFATE 0.083% SOL",
      "ndc": "76204020025", "last_qty": "75.000", "days_supply": 5,
      "last_fill_date": "01/30/2026", "next_due": "2026-02-04",
      "days_remaining": -3, "status": "OVERDUE" }
  ],
  "total": 1
}
```

### `DELETE /pharmacy/{ph_id}/refills/{patient_key}?drug_ndc=`

Removes a patient from future worklist results — for one `drug_ndc`, or
every drug if omitted. **Idempotent** (`INSERT ... IGNORE` against a
unique `(medical_store_id, patient_key, drug_ndc)` constraint — repeat
calls no-op). Does **not** touch dispense history; it's purely an opt-out
marker.

```json
{ "pharmacy_id": 1, "patient_key": "2f7d994fb191d02d", "drug_ndc": null, "dismissed": true }
```

---

## Activity & audit report (Basic+, `compliance_reports`)

### `GET /pharmacy/{ph_id}/activity?date_from=&date_to=&action=&customer=&wholesaler=&medicine=&actor_user_id=&has_errors=&skip=0&limit=50`

General-purpose operational feed, `limit` bounded `1..200`, true
pagination (`total` is a separate `COUNT` query). Ordered newest-first.
Known `action` values written by `log_activity(...)` call sites:
`DOCUMENT_UPLOADED`, `INVOICE_SAVED`, `DISPENSE_SAVED`,
`DISPENSE_FORCE_SAVED`, `DISPENSE_REPORT_UPDATED`, `DISPENSE_PATCHED`,
`DISPENSE_DOCUMENT_PATCHED`, `INVENTORY_ADJUSTED`,
`REFILL_CUSTOMER_DISMISSED`. A logged action only persists if the parent
transaction that triggered it also commits — `log_activity()` itself only
`db.add()`s, never commits independently.

```json
{
  "pharmacy_id": 1,
  "items": [
    { "activity_id": 42, "created_at": "2026-07-20T10:00:00", "action": "DISPENSE_SAVED",
      "actor_user_id": 1, "actor_role": "OWNER", "actor_name": "Jane Doe",
      "entity_type": "drug_report", "entity_id": 7, "summary": null,
      "customer_name": null, "wholesaler_name": null, "error_count": 0,
      "has_errors": false, "meta": { "report_id": 7 } }
  ],
  "total": 1, "skip": 0, "limit": 50
}
```

### `GET /pharmacy/{ph_id}/audit-report?date_from=&date_to=`

Error-centric compliance summary, not paginated (returns everything in
the date window).

```json
{
  "pharmacy_id": 1,
  "date_from": null, "date_to": null,
  "summary": {
    "documents_uploaded": 40, "documents_failed": 2,
    "dispense_reports_saved": 12, "dispense_reports_force_saved": 1,
    "invoices_saved": 8, "total_validation_errors": 4
  },
  "parsing_errors": [
    { "document_id": 5, "doc_key": "abc123", "process_type": "dispense",
      "original_filename": "batch.pdf", "status": "FAILED_PERMANENTLY",
      "error_message": "OCR timeout", "retry_count": 3, "created_at": "2026-07-19T08:00:00" }
  ],
  "validation_errors": [
    { "report_id": 7, "document_id": 3, "medicine_id": 55,
      "drug_name": "BREZTRI AEROSPHERE", "ndc": "00310461612",
      "errors": [ { "code": "UNIT_OF_USE_FRACTIONAL", "severity": "ERROR", "...": "..." } ],
      "created_at": "2026-07-18T09:00:00" }
  ]
}
```
`parsing_errors` = `Document` rows in the window with status `FAILED` or
`FAILED_PERMANENTLY`. `validation_errors` = one row per `Medicine` with
`has_errors=True` on a `force_saved=True` `DrugReport` — i.e. this is
specifically the record of errors that were overridden and persisted
anyway via `force_save`, not every validation warning ever raised.

---

## Temperature logs (public, unauthenticated)

No `Depends(auth_incoming_req)` and no pharmacy scoping — per the file's
own header comment, "auth and pharmacy wiring come later." Treat as a
device-facing ingestion endpoint, not a tenant-scoped API.

### `POST /temperature-logs`

```json
{ "temp_device_id": "FRIDGE-01",
  "logs": [ { "temperature": 4.2, "recorded_at": "2026-07-29T10:00:00",
              "probe": "PRB-001", "status": "Normal" } ] }
```
One DB row per reading in `logs`. **Real HTTP 200** (body `status_code:
201`): `{ "data": { "stored": 1, "temp_device_id": "FRIDGE-01" } }`.
`500` on a DB error (rolled back).

### `GET /temperature-logs?temp_device_id=`

Returns **all** matching rows, unpaginated, newest `created_at` first
(not `recorded_at`).

---

## Monitor (dashboard)

Endpoints under `/api/monitor/*` power the HTML dashboard at
`/dashboard`. Unlike every other route in this API, they return **raw**
dicts/lists — not the `Response_Schema` envelope — and every one of them
requires ADMIN (`require_admin`, mounted at the router level, so it's
enforced before any handler code runs). Not pharmacy-scoped — built for
backend operators, spans all stores.

| Path | Returns | Notes |
|---|---|---|
| `/overview` | counts by status, `completed_1h/24h`, `failed_24h`, `success_rate`, `avg_processing_seconds`, `timestamp` | `failed` combines `FAILED` + `FAILED_PERMANENTLY`; `success_rate` defaults to `100.0` if nothing finished in 24h |
| `/services` | health probe array (API Server, Database, Kafka Broker, Document Storage, Document Workers) | "API Server" is always reported healthy without an actual check; DB via `SELECT 1`; Kafka via producer-connected flag; storage via directory existence |
| `/documents/recent?limit=30` | latest documents across all stores | plain `LIMIT`, no `skip`/offset |
| `/documents/by-status` | `{status: count, ...}` | `GROUP BY Document.status` |
| `/documents/by-type` | `{document_type: count, ...}` | `GROUP BY Document.document_type` |
| `/documents/timeline?hours=24` | hourly `{hour, completed, failed, queued}` buckets, oldest→newest | `queued` per bucket = docs *created* in that hour, not a live queue-depth snapshot; issues `hours × 3` sequential COUNT queries |
| `/alerts` | `{alerts: [...firing...], rules: [...all 5...], total_firing, timestamp}` | 5 static rules always listed regardless of firing state — see below |
| `/config` | non-sensitive runtime config (Kafka servers/topics, storage dir, size/retry limits) | static, no DB access |
| `/metrics` | `uptime_seconds` (since **process start of the monitor module**, not OS process start), `cpu_count`, `memory`, `disk`, `python_version`, `gc_counts`/`gc_stats` | `memory.rss_mb` relies on the POSIX `resource` module — always `0` on Windows |
| `/logs?limit=100&level=INFO` | in-memory ring buffer from `core/log_buffer.py` | lost on process restart; not DB/file-backed |

`/alerts` rule catalog (fires live, thresholds computed per call):
`queue-depth-critical` (QUEUED > 50), `queue-depth-high` (10 < QUEUED ≤
50, mutually exclusive with critical), `error-rate-high` (1h error rate
> 10%, severity escalates to `critical` above 30%), `stale-processing`
(a `PROCESSING` doc untouched > 5 min), `kafka-disconnected` (producer
not connected).

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

# 2. Create a store, then subscribe it (validation/inventory routes are
#    all feature-gated — a store with no active subscription gets a
#    flat 402 on nearly everything below)
POST /pharmacy/create-pharmacy   { pharmacy_title, pharmacy_location }
                                                       → pharmacy_id
POST /subscription/subscribe     { medical_store_id, plan_code: "ULTIMATE" }
                                                       → checkout_url
# ...or, faster for local testing, have an admin comp it directly:
POST /admin/subscriptions        { medical_store_id, plan_code: "ULTIMATE" }
                                                       → subscription active immediately, no Stripe

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
                                                          OR 409 if any rx_no already exists

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
| 200 | OK — **also the real HTTP status for several logically-"201" success responses; see the Conventions note above** |
| 201 | row created (only genuinely real for `POST /invoices`, `POST /dispenses`) |
| 400 | malformed request (wrong file count, unsupported extension, expired/bad OTP, etc.) |
| 401 | missing/invalid/expired bearer or refresh token |
| 402 | feature/plan gate failed (`ensure_feature`) — no active subscription, or plan doesn't include the flag |
| 403 | auth-header-missing (`HTTPBearer`), role/ownership check failed (`ensure_pharmacy_access`), or admin-only route |
| 404 | row not found (including "token valid but user deleted") |
| 409 | uniqueness conflict (signup email, duplicate `rx_no` on save, pending transfer already exists, plan code exists, already-transferred pharmacy) |
| 413 | file too large |
| 422 | Pydantic/query validation, OR dispense-save blocked by the validation engine, OR an unknown `Feature` key in a plan payload |
| 429 | signup/OTP rate limit or resend cooldown (`Retry-After` set) |
| 500 | unhandled exception (logged via loguru) |
| 503 | Kafka broker / server-shutdown-mid-request |
