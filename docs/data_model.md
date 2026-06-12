# Data Model

> Audience: backend devs adding columns / migrations, frontend devs
> figuring out which table a field really lives in, and reviewers tracing
> "where does this value come from".
>
> All tables live in one MySQL schema accessed via `mysql+asyncmy://`.
> SQLAlchemy models are under `models/`; Alembic migrations under
> `alembic/versions/`. The Python class names sometimes diverge from
> table names — those are called out below.

## Table inventory at a glance

| Table | Class | Purpose | Source PDF/JSON shape |
|---|---|---|---|
| `user` | `User` | Pharmacy owners, technicians, admins | — |
| `medical_store` | `Pharmacy` (Python) | One row per medical store / retail pharmacy | — |
| `refresh_tokens` | `RefreshToken` | Hashed refresh JWTs per user | — |
| `documents` | `Document` | One row per file uploaded to `POST /documents/process` (Kafka pipeline state machine) | — |
| `invoices` | `Invoice` | Header of a purchase invoice | top-level fields of the invoice extraction JSON |
| `invoice_line_items` | `InvoiceLineItem` | Each line item on an invoice | `line_items[]` |
| `invoice_summaries` | `InvoiceSummary` | Bottom-of-invoice totals block | `summary` |
| `drug_reports` | `DrugReport` | Header of one dispense report (one upload) | top-level fields of the dispense extraction JSON |
| `medicines` | `Medicine` | One NDC per report | `medicines[]` |
| `dispenses` | `Dispense` | One filled prescription | `medicines[].dispenses[]` |
| `medicine_inventory` | `MedicineInventory` | Running stock per `(medical_store_id, code)` | — |
| `medicine_ndc_cache` | `MedicineNdcCache` | Cached FDA Drug NDC Directory lookups | — |

## ER diagram (logical)

```
                       ┌───────────────────┐
                       │   user (User)     │
                       │   user_id (PK)    │◄──┐
                       └───────┬───────────┘   │
                               │               │ technician.medical_store_id
                          owner│ user_id       │
                               ▼               │
                       ┌───────────────────────┴────┐
                       │ medical_store (Pharmacy)   │
                       │ medical_store_id (PK)      │◄──────────────────────┐
                       └───────────────────────────┬┘                       │
                                                   │ medical_store_id       │ medical_store_id
              ┌────────────────────────────────────┤                        │
              │                                    │                        │
              ▼                                    ▼                        ▼
   ┌──────────────────────┐     ┌──────────────────────────────┐   ┌──────────────────┐
   │  documents (Document)│     │ medicine_inventory           │   │  invoices        │
   │  doc_key (uq)        │     │ uq(med_store_id, code)       │   │  document_id ─┐  │
   │  storage_path        │     │ quantity, last_invoice_id ──┐│   │                │  │
   │  result_data (JSON)  │     └──────────────────────────────┘│   └─────┬──────────┘  │
   └────────────┬─────────┘                                      │         │             │
                │ document_id (nullable)                         │         │ invoice_id  │
                │                                                │         ▼             │
   ┌────────────┴───────────────┐                                │ ┌───────────────────┐ │
   │  drug_reports (DrugReport) │                                │ │ invoice_line_items│ │
   │  medical_store_id          │                                │ └───────────────────┘ │
   └────────────┬───────────────┘                                │                       │
                │ report_id                                      │ ┌───────────────────┐ │
                ▼                                                │ │ invoice_summaries │ │
   ┌────────────────────────────┐                                │ └───────────────────┘ │
   │  medicines (Medicine)      │                                │                       │
   │  ndc                       │                                └───────────────────────┘
   └────────────┬───────────────┘
                │ medicine_id
                ▼
   ┌────────────────────────────┐         ┌──────────────────────────────┐
   │  dispenses (Dispense)      │         │  medicine_ndc_cache          │
   │  qty_disp, days_supply,    │         │  ndc11 (PK)  — global cache  │
   │  rx_no, pat_*, ins_paid …  │         │  brand_name, end_date, ...   │
   └────────────────────────────┘         └──────────────────────────────┘

   ┌────────────────────────────┐
   │  refresh_tokens            │
   │  user_id FK → user         │
   └────────────────────────────┘
```

## Tables in detail

### `user`

| Column | Type | Notes |
|---|---|---|
| `user_id` | INT PK | auto-increment |
| `username` | VARCHAR(100) | derived from email part before `@` on signup |
| `email` | VARCHAR(255) | UNIQUE INDEX |
| `contact_number` | VARCHAR(10) | |
| `password_hash` | VARCHAR(255) | argon2 |
| `role` | ENUM(`OWNER`, `TECHNICIAN`, `ADMIN`) | from `core.enums.UserRole`; default `OWNER` |
| `medical_store_id` | INT FK → `medical_store` | only set for `TECHNICIAN`; null for owners and admins |

Relationships:
- `refresh_tokens` (1-N) → `refresh_tokens.user_id`
- `pharmacies_owns` (1-N) → `medical_store.user_id`
- `pharmacies_works` (1-N) → `medical_store` via reverse of `User.medical_store_id`

### `medical_store` — class name is `Pharmacy`

Renamed at the *table* level from `pharmacy` → `medical_store` for clarity
(the entity is a retail medical store). The Python identifier was kept
as `Pharmacy` to avoid churn through ~30 schema files.

| Column | Type | Notes |
|---|---|---|
| `medical_store_id` | INT PK | auto-increment |
| `user_id` | INT FK → `user` | The owner. Uses `use_alter=True` to break the User↔Pharmacy FK cycle at create-table time |
| `name` | VARCHAR(255) | |
| `address` | VARCHAR(255) | |

Relationships (both `lazy="selectin"` to avoid `MissingGreenlet` under async — see §"Async pitfalls" below):
- `owner` → `User` via `user_id`
- `technician` → `User` via `User.medical_store_id`

### `refresh_tokens`

| Column | Type | Notes |
|---|---|---|
| `refresh_token_id` | INT PK | |
| `user_id` | INT FK → `user` | CASCADE on delete |
| `token` | VARCHAR(255) | argon2 hash of the actual refresh JWT |
| `revoked` | BOOL | login flow inserts new tokens; revocation logic TBD |

### `documents`

State machine row for every file uploaded via `POST /documents/process`.
Domain rows are *not* created here — that's `POST /invoices` and
`POST /dispenses`. Document tracks the Kafka pipeline state.

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `doc_key` | VARCHAR(64) UNIQUE | the UUID the API issues; client polls by this |
| `medical_store_id` | INT FK → `medical_store` | required; everything is store-scoped |
| `uploaded_by_user_id` | INT FK → `user` | nullable (SET NULL on user delete) |
| `document_type` | VARCHAR(20) | file extension: `pdf`, `xlsx`, `jpg`, ... |
| `process_type` | VARCHAR(20) INDEX | `invoice` / `dispense` / `barcode` — routes to a specific Kafka worker |
| `original_filename` | VARCHAR(255) | |
| `storage_path` | VARCHAR(500) | local FS path; e.g. `storage/documents/<doc_key>.pdf` |
| `file_size` | INT | bytes |
| `status` | VARCHAR(30) INDEX | from `core.enums.DocumentStatus`: `QUEUED → PROCESSING → COMPLETED \| FAILED → RETRYING → FAILED_PERMANENTLY` |
| `retry_count` | INT | 0-based count of prior attempts |
| `max_retries` | INT | from `settings.DOCUMENT_MAX_RETRIES` |
| `error_message` | TEXT | last exception when `status` is FAILED* |
| `result_data` | MEDIUMTEXT | JSON the handler returned (~70 KB for a typical dispense report; TEXT was too small, so we use MEDIUMTEXT (16 MB)) |
| `progress` | JSON | barcode handler stashes `{"second_image_path": "..."}` here when the upload contained 2 images |
| `created_at`, `updated_at` | DATETIME | server-side defaults |

### `invoices` — class `Invoice`

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `medical_store_id` | INT FK → `medical_store` | required |
| `document_id` | INT FK → `documents` | nullable (set when the invoice was created via the upload+save flow; null for manual creates) |
| `created_at` | DATETIME | |
| `source_filename`, `page_count` | descriptive | |
| Seller block | `seller_name/address/phone/dea/permit/fed_id` | from extractor |
| Invoice meta | `invoice_number/invoice_date/order_number/due_date/terms_of_payment/your_order_number` | |
| Customer block | `customer_number/name/dea/state_reg` | |
| Bill-to / Ship-to / Remit-to | full address blocks | |
| `raw_payload` | MEDIUMTEXT | echo of the request body for forensics |

Relationships (both `lazy="selectin"`):
- `line_items` (1-N) → `InvoiceLineItem`
- `summary` (1-1) → `InvoiceSummary`

### `invoice_line_items` — class `InvoiceLineItem`

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `invoice_id` | INT FK → `invoices` (CASCADE) | |
| Position | `line`, `item_code` | as printed |
| NDC | `raw_ndc`, `ndc11` INDEX, `upc` INDEX | `_classify_ndc` decides which is populated |
| Quantities | `orig_order_qty`, `order_qty`, `invoiced_qty` | strings — extractor may emit decimals as text |
| Display | `uom`, `description`, `size`, `form` | |
| Money | `unit_price`, `extended_price`, `awp` | strings |
| Verification | `verification_required` BOOL, `verified` BOOL | true once a barcode/datamatrix scan matched FDA |
| FDA | `fda_package_ndc`, `fda_ndc11` | filled by `/barcode/...` flow at save time |
| DataMatrix | `dm_gtin`, `dm_serial_number`, `dm_expiration_date`, `dm_lot_number` | from `services/datamatrix_scanner.py` |

### `invoice_summaries` — class `InvoiceSummary`

One row per invoice (uniqued on `invoice_id`).

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `invoice_id` | INT FK → `invoices` UNIQUE | |
| `order_line_total`, `fuel_surcharge`, `sub_total`, `tax`, `grand_total`, `total_due_by` | strings | |

### `drug_reports` — class `DrugReport`

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `medical_store_id` | INT FK → `medical_store` | required |
| `document_id` | INT FK → `documents` | nullable |
| `created_at` | DATETIME | |
| `report_date`, `report_from_date`, `report_to_date` | VARCHAR(20) | original strings; the report is for a date range |
| `grand_total_rx_count` | INT | as printed (spec §4.4: do NOT trust; recompute) |
| `grand_total_price`, `grand_total_cost` | NUMERIC(12, 2) | as printed |

Relationship: `medicines` (1-N, `lazy="selectin"`).

### `medicines` — class `Medicine`

One row per NDC per report. Drug-level totals live here.

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `report_id` | INT FK → `drug_reports` CASCADE | |
| `drug_name` | VARCHAR(300) | exactly as printed; intentionally mixed case (tall-man lettering) |
| `ndc` | VARCHAR(11) INDEX | 11-digit, no hyphens |
| `inventory_bucket` | VARCHAR(100) | semantics unconfirmed — informational |
| `lot_no_exp_date` | VARCHAR(100) | low-trust; do NOT key on this |
| Drug totals | `total_packs`, `total_rx_count`, `total_ins_paid`, `total_price`, `total_cost` | NUMERIC |

Relationship: `dispenses` (1-N, `lazy="selectin"`).

### `dispenses` — class `Dispense`

One row per filled prescription.

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `medicine_id` | INT FK → `medicines` CASCADE | |
| Quantities | `qty_disp`, `qty_ord` NUMERIC(10, 3) | |
| `days_supply` | INT | |
| `date_filled` | VARCHAR(12) | MM/DD/YYYY as printed |
| Identifiers | `rx_no` INDEX, `ref` | `ref` = refills remaining per spec §6.6 |
| Patient | `pat_name`, `pat_addr` TEXT, `pat_phone` | raw PHI — never logged outside of MySQL |
| Prescriber | `pres_name`, `pres_addr` TEXT, `pres_phone` | |
| Money | `price`, `ins_paid` NUMERIC(12, 2), `ins_code` | `ins_code` is canonicalized only in validation, never written here |

### `medicine_inventory` — class `MedicineInventory`

Running stock ledger. Key insight: the `(medical_store_id, code)`
pair is UNIQUE — saving two invoices that contain the same NDC adds to
the same row.

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `medical_store_id` | INT FK → `medical_store` CASCADE, INDEX | |
| `code` | VARCHAR(20) INDEX | NDC11 preferred, UPC fallback |
| `product_name` | VARCHAR(300) | latest description (cosmetic) |
| `quantity` | NUMERIC(14, 3) | signed; negative = "dispensed without matching invoice" |
| `last_invoice_id` | INT FK → `invoices` SET NULL | last invoice that touched this row |
| `created_at`, `updated_at` | DATETIME | |
| UNIQUE | `(medical_store_id, code)` | backs the `INSERT ... ON DUPLICATE KEY UPDATE` upsert |

Update rules:
- `POST /invoices` calls `add_invoice_quantities` → `+invoiced_qty` per line item.
- `POST /dispenses` calls `subtract_dispense_quantities` → `-sum(qty_disp)` per medicine.

### `medicine_ndc_cache` — class `MedicineNdcCache`

Global (not per-store) cache of FDA Drug NDC Directory results. Read on
every Tier-2 validation; written on miss / TTL expiry.

| Column | Type | Notes |
|---|---|---|
| `ndc11` | VARCHAR(11) PK | natural primary key |
| `matched_package_ndc` | VARCHAR(20) | the 10-digit hyphenated form FDA actually matched on |
| `brand_name`, `generic_name`, `dosage_form`, `route` | descriptors | from FDA |
| `marketing_category`, `marketing_start_date`, `marketing_end_date`, `listing_expiration_date` | YYYYMMDD strings | drives Module A discontinued / expires-soon checks |
| `package_description` | TEXT | drives Module C unit-of-use detection |
| `is_unit_of_use` | BOOL | precomputed at fetch time from `dosage_form`+`package_description` keywords (inhaler/pen/kit/sensor/strip/lancet/...) |
| `found_in_fda` | BOOL | False for medical devices / supplies that aren't in the Drug NDC DB |
| `raw_payload` | MEDIUMTEXT | full FDA `results[0]` dict (~3-8 KB), kept for forensics |
| `fetched_at`, `updated_at` | DATETIME | TTL math uses `updated_at` |

## Foreign-key cycles and `use_alter`

`user.medical_store_id → medical_store.medical_store_id` and
`medical_store.user_id → user.user_id` form a cycle. MySQL/InnoDB can
hold it at runtime, but Alembic must emit the create-tables in some
order. We break the cycle at create time by marking the `medical_store →
user` FK with `use_alter=True, name="fk_pharmacy_user_id"`. Alembic
creates both tables first, then issues `ALTER TABLE medical_store ADD
CONSTRAINT ...` afterwards. This is the only such pair in the schema.

## Async-SQLAlchemy pitfalls already handled

Pydantic's `model_validate(orm_obj)` walks fields via `getattr`, which
triggers a lazy load if the relationship wasn't loaded. Under
`AsyncSession`, lazy loads need a greenlet context that isn't available
post-`await`, so they raise `MissingGreenlet`.

**Invariant we enforce**: every relationship referenced by a Pydantic
response model with `from_attributes=True` is declared `lazy="selectin"`
on the SQLAlchemy side. Currently this covers:

| Relationship | Read by |
|---|---|
| `Invoice.line_items` | `InvoiceResponse` |
| `Invoice.summary` | `InvoiceResponse` |
| `DrugReport.medicines` | `DrugReportResponse` |
| `Medicine.dispenses` | `MedicineResponse` |
| `Pharmacy.owner` | `PharmacyOutput`, `PharmacyGetOutputSchema` |
| `Pharmacy.technician` | (none today — preloaded for symmetry) |

Adding a new relationship → response-field combo without
`lazy="selectin"` will pass type checks but 500 at runtime. Either set
`lazy="selectin"` on the relationship or call `selectinload(...)` in the
specific query.

## Soft conventions in this schema

- **Decimal-as-string** for money/quantity fields on Invoice and
  Dispense. Extractors emit `"30.0"` not `30` — `services/validation/tier1.py`
  uses a `_to_decimal` helper that tolerates both.
- **Patient data lives only in `dispenses`.** Alerts and logs use
  `patient_key = sha1(name + phone + ZIP5)[:16]`; raw `pat_name`,
  `pat_phone`, `pat_addr` never leave MySQL.
- **`drug_reports.grand_total_*` is the printed total**, which spec
  §4.4 calls out as unreliable. Always recompute by summing
  `dispenses.price` / `ins_paid` / `qty_disp`.
- **`code` in `medicine_inventory` and validation alerts** = NDC11
  if available, else UPC. Defined in
  `services/inventory_service.py::_pick_code` and
  `services/validation/tier2.py`.

## Conventional joins

Most reporting queries follow one of these patterns. All are
pharmacy-scoped via the `medical_store_id` columns the models carry.

```sql
-- current inventory snapshot for a store
SELECT * FROM medicine_inventory WHERE medical_store_id = ?;

-- recompute grand total of a report (spec G)
SELECT COUNT(d.id) AS rx, SUM(d.price) AS sum_price, SUM(d.ins_paid) AS paid
FROM dispenses d
JOIN medicines m ON m.id = d.medicine_id
WHERE m.report_id = ?;

-- module H worklist (zero refills) for a report
SELECT m.ndc, m.drug_name, d.rx_no, d.pat_name
FROM dispenses d
JOIN medicines m ON m.id = d.medicine_id
WHERE m.report_id = ? AND d.ref = '0';

-- module F worklist (potential duplicate-bill)
SELECT m.ndc, d.pat_name, d.ins_code, COUNT(*) AS cnt
FROM dispenses d
JOIN medicines m ON m.id = d.medicine_id
WHERE m.report_id = ?
GROUP BY m.ndc, d.pat_name, d.ins_code
HAVING cnt >= 2;
```

## Migration history

Single linear chain in `alembic/versions/`:
1. `7fcbc56191d9_extract_save_inventory_flow.py` — full baseline
2. `e10afcb860b5_use_mediumtext_for_result_data_and_raw_.py` — bump TEXT→MEDIUMTEXT
3. `41f560f3a557_add_medicine_ndc_cache.py` — add the FDA cache table

No conflicting branches. `alembic upgrade head` from a fresh schema
produces the structure documented above.
