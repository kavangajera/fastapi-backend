# Dispense Report Validation Engine

> Audience: backend devs maintaining the engine, and frontend devs
> binding alerts to the dispense edit UI.
> Companion to `Drug Dispensed Report Analysis Spec.docx` (§§ refs in
> parentheses point back to that spec) — but where the spec and the
> current code disagree, **this document follows the code**, and calls
> out the divergence explicitly so nobody re-derives it from scratch.

---

## 1. What the engine does

When a dispense report (PDF / DOCX / XLS) is uploaded, the Kafka worker
extracts the structured JSON shown in `data` of the
`POST /documents/process` response. **No domain rows are persisted at
that point.** The validation engine then runs over that JSON and emits a
`ValidationReport` so the UI can show the user exactly what's wrong
*before* they press Save.

The engine runs from four HTTP-reachable call sites plus one Kafka call
site, all sharing the same Pydantic types (`schemas/validation.py`) so
the UI can write one renderer:

| Where | What runs | `granted` (plan features) | DB write? |
|---|---|---|---|
| Kafka worker, `kafka_worker/handlers/dispense_handler.py` (during `POST /documents/process` for `process_type=dispense`) | **Tier 1 only** | `None` — unrestricted, every module runs, no `PLAN_LOCKED` alerts (this is a preview, not gated by a paid plan) | No |
| `POST /dispenses/validate` | **Tier 1 + Tier 2** | The caller's actual `Plan.features` | No |
| `POST /dispenses` | **Tier 1 + Tier 2** | The caller's actual `Plan.features` | Yes, unless blocked (see §4) |
| `PUT /dispenses/{report_id}` | **Tier 1 + Tier 2** | The caller's actual `Plan.features` | Yes, unless blocked — full replace |
| `PATCH /dispenses/document` | **Tier 1 + Tier 2**, run only against the subset of the re-uploaded document whose `rx_no`s already exist in DB | The caller's actual `Plan.features` | Yes, unless blocked — patches matched dispenses only |

Tier 1 is pure data-shape/arithmetic checking (no network calls) — safe
to run inline inside the Kafka handler's blocking-worker thread. Tier 2
adds up to one FDA HTTP lookup per distinct NDC in the report (cached —
see §6), which is why it's deliberately **not** run during upload: at
~1–2s per uncached NDC, a large report could blow past
`PROCESSING_RESULT_TIMEOUT_SECONDS` (180s). Tier 2 always includes Tier 1
— `validate_tier2(...)` runs `validate_tier1(...)` first (or accepts an
already-computed Tier-1 report) and merges its alerts into the combined
list, plus reuses its `grand_total`/`per_patient` blocks unchanged.

**Every HTTP call site above additionally gates the *entire endpoint*
behind `Feature.TOP_QUANTITY_DRUG_REPORT` (min plan Advanced) via
`ensure_feature` before validation ever runs.** This is a separate,
coarser gate than the per-module `granted` micro-gating described in §12
— a Basic-plan store gets a flat `402` and never even reaches the
validation engine, regardless of which individual modules it might
otherwise qualify for.

---

## 2. The report shape

A `ValidationReport` always has this shape (`schemas/validation.py`,
every model `extra="forbid"`):

```python
class Alert(BaseModel):
    module: Literal["A","B","C","D","E","F","G","H","I","J","FIELD","INGEST"]
    code: str
    severity: Literal["ERROR","WARNING","INFO","INDETERMINATE","PASS"]
    message: str
    medicine_index: int | None = None
    dispense_index: int | None = None
    ndc: str | None = None
    rx_no: str | None = None
    patient_key: str | None = None   # hashed, never raw PHI
    field: str | None = None
    expected: Any | None = None
    actual: Any | None = None
    suggestion: str | None = None

class ValidationSummary(BaseModel):
    errors: int = 0
    warnings: int = 0
    info: int = 0
    indeterminate: int = 0
    blocking: bool = False   # == errors > 0
    tier1_ran: bool = False
    tier2_ran: bool = False

class ValidationReport(BaseModel):
    summary: ValidationSummary
    alerts: list[Alert]
    grand_total: GrandTotalRecompute | None = None
    per_patient: list[PerPatientTotal] = []
```

`module` reserves the values `"I"`, `"J"`, and `"INGEST"` — they are
declared in the schema but **no code currently emits them** (see §10).
All money/quantity fields on `GrandTotalRecompute` / `PerPatientTotal`
(`total_price`, `recomputed_sum_price`, etc.) are `str`, not
`float`/`Decimal` — every value is `str()`-cast from a `Decimal` before
assignment, so the API always serializes an exact decimal string and
never introduces JSON float rounding.

`summary.blocking` (`services/validation/severity.py::summarize`) is
derived **strictly from `errors > 0`** — `INDETERMINATE` (e.g.
`PLAN_LOCKED`, `NDC_LOOKUP_FAILED`) never blocks a save, nor do
`WARNING`/`INFO`/`PASS`. `PASS` is tallied internally while counting but
has no field on `ValidationSummary` — no module currently emits an
explicit `PASS` alert (a clean NDC just produces zero alerts for that
medicine, not a `PASS` record).

---

## 3. Modules — every check in the engine

Each module emits zero or more `Alert` objects, with enough location
info (`medicine_index`, `dispense_index`, `ndc`, `rx_no`, `field`) for
the UI to highlight the offending row/field.

### FIELD — sanity checks on the raw extracted data (`services/validation/tier1.py::_check_field_sanity`)

Runs **unconditionally, never plan-gated** — the code comment explains
why: these checks "protect the inventory-subtraction math on save,
independent of any paid feature." Every later module assumes the data
shape these checks establish is sound.

| Code | Severity | Trigger |
|---|---|---|
| `MALFORMED_NDC` | ERROR | `medicine.ndc` doesn't fullmatch `^\d{11}$` |
| `DRUG_NAME_BLEED` | ERROR | `drug_name` contains one of the marker strings `"Pres Addr"`, `"Pat Addr"`, `"Pat Ph#"`, `"Ins Paid"`, `"Ins Code"`, `"Qty Ord"`, `"Inventory Bucket"` (an adjacent column label leaked in during extraction), OR `len(drug_name) > 80` |
| `DUPLICATE_NDC_IN_REPORT` | **ERROR** | The same well-formed 11-digit NDC appears in ≥ 2 medicine rows of one report (usually caused by name-bleed splitting one drug into multiple rows during extraction, e.g. one row per date) |
| `MEDICINE_NO_DISPENSES` | WARNING | A medicine has zero dispenses attached |

**Why `DUPLICATE_NDC_IN_REPORT` is ERROR, not WARNING**: if it slipped
past, the save route would create two `Medicine` rows for the same
product. Inventory subtraction would then deduct twice (once per row),
corrupting the running stock for that NDC. **Fix path**: merge the two
medicine entries in the JSON — copy the second row's `dispenses[]` into
the first row's `dispenses[]`, delete the second row.

> Note: this module's own docstring in the source claims a "missing
> rx_no" check as part of FIELD-sanity — **no such check exists in the
> current implementation**. Don't build a UI treatment around it; a
> missing `rx_no` is silently tolerated by every downstream module
> (it just fails to group into `by_patient_ndc`/duplicate lookups the
> way a present one would).

### D — qty / days_supply plausibility (Tier 1, §7.4) — flag `days_supply_validation` (min Ultimate)

| Code | Severity | Rule |
|---|---|---|
| `DAYS_SUPPLY_INVALID` | ERROR | `days_supply` is missing or `<= 0` |
| `DAYS_SUPPLY_RATE_OUT_OF_BOUNDS` | WARNING | `qty_disp / days_supply` outside `[DAYS_SUPPLY_RATE_MIN, DAYS_SUPPLY_RATE_MAX]` (default `[0.05, 50]`) |

A dispense that trips `DAYS_SUPPLY_INVALID` is skipped for the rate
check (there's no valid denominator). A dispense with `qty_disp <= 0` or
unparsable is also skipped for the rate check, silently.

**Why this rule is loose**: the spec calls this "Tier 3" because we
don't have the SIG (directions). An exact check would be "take 1 tab
daily, 30 days, expect qty=30"; without SIG we can only catch obvious
nonsense. If the pharmacy starts exporting SIG, Module D upgrades to an
exact Tier-1 check with no schema change needed.

### E — same patient + same drug (Tier 1, §7.5) — flag `refill_analysis_billings` (min Advanced)

| Code | Severity | Rule |
|---|---|---|
| `REPEAT_PATIENT_DRUG` | WARNING | `patient_key + ndc` appears ≥ 2 times in the report |

**Why warning, not error**: a legitimate refill on day N+30 is also the
same patient + same drug. Worth a worklist entry, not an auto-rejection.
The alert's `actual` field lists every matched `rx_no` in the group, and
its location (`medicine_index`/`dispense_index`) points at the *first*
matching entry.

### F — same patient + same drug + same insurance (Tier 1, §7.6) — flag `refill_analysis_billings` (min Advanced)

| Code | Severity | Rule |
|---|---|---|
| `REPEAT_PATIENT_DRUG_INSURANCE` | **ERROR** | `patient_key + ndc + canonical_insurance` (see §8) appears ≥ 2 times |

**Why this is the strongest fraud signal**: same patient + same drug +
same plan is almost always a billing duplicate. F's grouping is a
*subset* of E's — F requires everything E requires, plus a matching
canonical insurance code — so **any report that trips F also trips E**
for that same patient/NDC pair (E fires on the coarser group first).
Both share the same `refill_analysis_billings` gate, so they always run
together.

### G — billing reconciliation + per-patient + unpaid (Tier 1, §7.7) — flag `top_quantity_drug_report` (min Advanced)

Module G produces three kinds of output from one pass over every
dispense in the report:

1. **Grand-total recompute**. Independently sums every dispense's price,
   ins_paid, qty, and rx_count, then compares against the printed
   `grand_total.*`:

   | Code | Severity | Rule |
   |---|---|---|
   | `GRAND_TOTAL_DELTA_RX` | INFO | printed `total_rx_count` ≠ recomputed count |
   | `GRAND_TOTAL_DELTA_PRICE` | INFO | printed `total_price` ≠ recomputed sum |

   > **Field-naming gotcha**: on both alerts, `expected` holds the
   > *recomputed* (trustworthy) value and `actual` holds the *printed*
   > (possibly-wrong) value — the inverse of what "expected vs. actual"
   > intuitively suggests. Printed totals are frequently corrupted in
   > the source document; always trust the recomputed value, and build
   > any UI diff view with that field mapping in mind.

2. **Per-patient totals**, one entry per `patient_key`, sorted by total
   billed descending — this is what report **R3** ("Per-patient billing
   summary") is built from:
   ```json
   { "patient_key": "16a955...", "patient_label": "ESPOSITO, F.",
     "rx_count": 1, "total_price": "4471.68", "total_ins_paid": "4471.68",
     "patient_responsibility": "0.00" }
   ```
   `patient_label` reflects whichever dispense for that patient was
   processed **last** in iteration order, not necessarily the
   "canonical" spelling.

3. **Unpaid lines** (`price > 0` but `ins_paid == 0`):

   | Code | Severity | Rule |
   |---|---|---|
   | `UNPAID_LINE` | WARNING | the price was charged but insurance paid nothing |

   This is deliberately a warning, not an error — possible reasons
   include a cash sale, a claim rejection, or a coupon override, and the
   engine can't distinguish those without more data. It surfaces them
   for human review rather than guessing.

### H — refills remaining = 0 (Tier 1, §7.8) — flag `refill_analysis_billings` (min Advanced)

| Code | Severity | Rule |
|---|---|---|
| `ZERO_REFILLS_REMAINING` | INFO | `ref` parses to `0` for that dispense |

Used to render report **R4** (zero-refill worklist) — every patient who
needs a new prescription before their next pickup. Parsing is
float-tolerant on purpose (`int(float(str(ref).strip())) == 0`) because
extracted values commonly arrive as `"0.0"` rather than `"0"`; a `ref`
that's `None` or fails to parse at all is silently skipped, not flagged.

### A — NDC validity / discontinuation (Tier 2, §7.1) — flag `discontinued_drug_detection` (min Ultimate)

This is where FDA gets called (via the shared cache — see §6). Per NDC:

| Code | Severity | Rule |
|---|---|---|
| `NDC_NOT_FOUND` | WARNING | the NDC isn't in the FDA Drug NDC Directory — may be a medical device/supply (sensors, strips, lancets — lives in the FDA Device DB instead), a discontinued/delisted product, or a very recent launch not yet indexed. The alert's `suggestion` field uses plain, non-technical language aimed at pharmacy staff rather than jargon. |
| `DRUG_DISPENSED_BEFORE_MARKETED` | WARNING | a dispense's `date_filled` is earlier than the FDA `marketing_start_date` for that NDC |
| `DRUG_DISPENSED_AFTER_DISCONTINUED` | **ERROR** | a dispense's `date_filled` is later than the FDA `marketing_end_date` |
| `NDC_LISTING_EXPIRES_SOON` | INFO | `marketing_end_date` is within `NDC_LISTING_EXPIRY_INFO_DAYS` (default 365) of today |

> **Spec-vs-code divergence, worth flagging explicitly**: the module's
> own docstring (and the older version of this doc) described a single
> flat check — `marketing_end_date < today` → `NDC_DISCONTINUED`. That
> code does **not exist** in the current implementation. Discontinuation
> is now evaluated **relative to each dispense's own `date_filled`**
> (`DRUG_DISPENSED_AFTER_DISCONTINUED`), not against "today" — a
> historical dispense that happened while the drug was still marketed
> won't be flagged just because the drug was later discontinued. If
> `date_filled` is missing/unparsable, the check falls back to treating
> "today" as the effective dispense date (the code path that would skip
> the check entirely, `strict_date_check=False`, is not currently
> reachable from any call site — it's hardcoded `True`).
>
> If the NDC isn't found in FDA's directory at all (`NDC_NOT_FOUND`), no
> further Module A checks run for that medicine — there's no
> `marketing_start_date`/`marketing_end_date` to compare against.

### B — drug_name ↔ NDC consistency (Tier 2, §7.2) — flag `ndc_claim_mismatch_checks` (min Ultimate)

| Code | Severity | Rule |
|---|---|---|
| `DRUG_NAME_MISMATCH` | WARNING | the printed `drug_name`'s significant tokens don't overlap the FDA `brand_name`/`generic_name` for that NDC by at least 34% |

Tokenization: both the printed name and each FDA candidate name are
split into uppercase alphanumeric tokens longer than 2 characters,
excluding purely-numeric tokens. A match requires
`|printed_tokens ∩ fda_tokens| / |fda_tokens| >= 0.34` — the ratio is
denominated on the **FDA name's** token count, not the printed name's.
Brand-vs-generic still counts as a match (e.g. *Lipitor* ↔
*Atorvastatin*) because FDA's `generic_name` field carries both sides.
Skipped entirely if the NDC wasn't found in FDA (Module A already
raised `NDC_NOT_FOUND`).

### C — package size vs dispensed quantity (Tier 2, §7.3) — flag `pack_size_billed_reconciliation` (min Advanced)

| Code | Severity | Rule |
|---|---|---|
| `UNIT_OF_USE_FRACTIONAL` | **ERROR** | the FDA cache flags the product `is_unit_of_use` (dosage form or package description mentions inhaler/aerosol/metered/pen/kit/sensor/strip/lancet/prefilled/auto-injector/syringe) **and** a dispense's `qty_disp` is not a whole number |

If the product is *not* flagged unit-of-use, Module C emits **nothing at
all** for that medicine — not even an INFO/PASS placeholder — bulk
products (tablets, bottles of liquid, etc.) simply aren't in scope for
this check.

### D (Tier 2) — fractional daily dose — **not independently plan-gated**

A second, distinct "Module D" lives in `tier2.py`, unrelated to the
`days_supply` module of the same letter in `tier1.py`:

| Code | Severity | Rule |
|---|---|---|
| `FRACTIONAL_DAILY_DOSE` | WARNING | `qty_disp / days_supply` is not a whole number |

This check has **no `has(granted, ...)` gate of its own** — it runs
unconditionally inside the same per-medicine FDA-lookup loop that
Modules A/B/C share. That means it's only reached at all when at least
one of A/B/C's flags is granted (the loop itself is skipped entirely if
none are), and it only evaluates NDCs that are well-formed 11-digit
strings (the loop's own precondition). Treat it as **transitively
gated** by whichever of A/B/C got the store into the loop, not by an
independent entitlement.

### `NDC_LOOKUP_FAILED` — the Module A error path

If the FDA/cache lookup for a medicine's NDC throws (network error,
malformed response, etc.), and Module A is granted (`need_a`), one
`Alert(module="A", code="NDC_LOOKUP_FAILED", severity="INDETERMINATE")`
is emitted and the loop `continue`s to the next medicine — **B, C, and
D are all skipped for that medicine on a lookup failure**, even if B or
C individually were granted, because the failure short-circuits before
they run.

### Modules I and J — reserved, not implemented

Need historical data the system doesn't yet retain (a prior period for
I, 12 months for J). `schemas/validation.py::Alert.module` already
reserves the `"I"`/`"J"` literal values so the eventual rollout won't
need a schema migration — but no code path emits them today. Once
multiple reports per store are retained, these can be added to the same
engine entry point with no interface change.

---

## 4. Severity → what the UI should do

| Severity | UI treatment | Save behavior |
|---|---|---|
| `ERROR` | Red. Highlight the field. Disable Save until fixed. | `POST /dispenses` / `PUT /dispenses/{id}` / `PATCH /dispenses/document` return **422** with the full `ValidationReport` in `detail.data` — **unless** the caller sets `force_save: true`, in which case the save proceeds and the ERROR alerts are stamped onto `DrugReport.validation_errors` / the affected `Medicine.validation_errors` for later audit. |
| `WARNING` | Amber. Soft callout — "verify this". | Save still succeeds. Alert returned in `DispenseSaveResponse.validation`. |
| `INFO` | Grey. Worklist entry, no action prompt. | Same as WARNING. |
| `INDETERMINATE` | Grey + "couldn't check" badge. | Same as WARNING — never blocks, even for `PLAN_LOCKED`/`NDC_LOOKUP_FAILED`. |
| `PASS` | Not currently emitted by any module (see §10). | n/a. |

`summary.blocking = (errors > 0)`, computed once in
`services/validation/severity.py::summarize`. If false, Save proceeds;
if true, Save either 422s or — with `force_save: true` — persists with
the errors stamped for audit (`GET /pharmacy/{ph_id}/audit-report`
surfaces exactly the force-saved rows and their stamped errors).

`PATCH /dispenses` (the plain rx_no patch route, as opposed to `PATCH
/dispenses/document`) is the one write path that **does not run the
validation engine at all** — it's a trusted, surgical field edit, not a
re-submission of the whole report.

---

## 5. `patient_key` — what it is and why it exists

A `patient_key` shows up on every alert tied to a specific patient, and
in every `per_patient` entry. It's a **stable per-patient identifier**
computed deterministically from the dispense row, **without storing the
patient's name, phone, or full address** in any alert payload, log line,
or DB row outside the dispense the caller itself submitted.

### How it's computed (`services/validation/patient_key.py`)

```python
def derive_patient_key(name, phone, address) -> str:
    parts = (normalize_name(name), digits_only(phone), extract_zip5(address))
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
```

- `normalize_name`: uppercase, strip, then collapse every internal
  whitespace run to a single space (not a plain `.strip()` — `"DUPONT
  HERARD,   MARIE"` and `"DUPONT HERARD, MARIE"` normalize identically).
- `digits_only(phone)`: concatenates every digit found anywhere in the
  phone string — no area-code or length validation.
- `extract_zip5(address)`: regex-searches the **address field itself**
  (there's no separate zip column) for `\b(\d{5})(?:[-\s]?\d{4})?\b` and
  keeps just the first 5-digit group, discarding any ZIP+4 suffix.
- The three parts are joined `name|phone|zip5` in that exact order, then
  SHA-1'd over UTF-8 bytes and **truncated to the first 16 hex
  characters** (64 bits — not the full 40-char SHA-1 digest).

So `("DUPONT HERARD, MARIE", "3478585259", an address containing
"11214")` always produces the same 16-char key, regardless of which
dispense row that combination appears on.

### Why this design

1. **Group dispenses across rows reliably.** The same person can appear
   under several `rx_no`s, sometimes with slightly different name
   formatting (`"DUPONT HERARD, MARIE"` vs `"HERARD, MARIE"`). Modules
   E, F, and G all need a stable key to group on — NDC and `rx_no` alone
   aren't enough, since an Rx number is per-prescription, not
   per-patient.
2. **PHI safety.** Alert payloads and the dashboard log stream are
   visible to backend operators, agents, and log collectors who
   shouldn't see raw patient names. The hash is one-way — given just the
   key, the name can't be recovered.
3. **The UI still gets a human-readable label.** `patient_label(name)`
   (same file) is computed separately, display-only, and carries
   deliberately less information than the key: it splits on `,` and
   returns `"LAST, F."` (last name + first-initial) when a comma-split
   name has a non-empty second part, else the name as-is, else `"?"` if
   the name was empty.

### Where it appears

- On every alert involving a dispense (`Alert.patient_key`).
- On every `per_patient` entry (report R3) and every refills-worklist
  row (`GET /pharmacy/{ph_id}/refills`).
- Never accompanied by `pat_name=` in a log line — only `patient_key=`.

### Known limitation

If the same person's name is spelled differently across pages of the
same source document (`"HERARD, MARIE"` vs `"DUPONT HERARD, MARIE"`),
`normalize_name` produces two different keys for the same physical
patient. The phone + ZIP5 components partially compensate, but a
phone-only or zip-only fallback grouping isn't implemented — if this
starts producing meaningful false negatives in practice, the fix is a
secondary grouping pass keyed on phone+zip5 alone, not a change to the
primary hash (which several already-persisted alerts depend on staying
stable).

---

## 6. FDA call lifecycle — when, why, and the cache

### When the call happens

- **Kafka worker (`POST /documents/process`, dispense)** → **no** FDA
  call — Tier 1 only.
- **`POST /dispenses/validate`, `POST /dispenses`, `PUT
  /dispenses/{id}`, `PATCH /dispenses/document`** → Tier 2 runs, so yes,
  subject to the cache below.
- **`POST /documents/process` (barcode)** → hits FDA from the barcode
  worker (a separate code path, not gated by `medicine_ndc_cache`).

### Why two-tier (and not always-run-FDA)

Each FDA call costs roughly **1–2 seconds** because
`api.fda.gov/drug/ndc.json` expects a hyphenated NDC10, and the exact
hyphenation depends on which segment of the NDC11 carries a leading
zero — the client tries multiple candidate forms before giving up (see
below). A worklist of ~85 medicines × 1.5s ≈ 2 minutes of HTTP — too
long for the upload path (`PROCESSING_RESULT_TIMEOUT_SECONDS = 180` is
borderline even without it). So Tier 1 runs inline (instant), Tier 2
runs on demand.

### NDC10 candidate generation (`services/validation/fda_client.py::ndc11_to_ndc10_candidates`)

Given an 11-digit NDC, up to 4 hyphenated candidates are tried, each
form dropping a leading zero from a different segment of the 5-4-2 NDC11
layout:

1. If digit 0 is `"0"` → 4-4-2 form: `ndc[1:5]-ndc[5:9]-ndc[9:11]`.
2. If digit 5 is `"0"` → 5-3-2 form: `ndc[:5]-ndc[6:9]-ndc[9:11]`.
3. If digit 10 is `"0"` → 5-4-1 form: `ndc[:5]-ndc[5:9]-ndc[10]`.
4. Always, unconditionally, last → the raw 5-4-2 form:
   `ndc[:5]-ndc[5:9]-ndc[9:11]`.

Candidate count ranges from 1 (no leading zeros in any segment) to 4
(all three conditions hold). The FDA client tries them **in this
order** and stops at the first one that returns a non-empty `results`
array; only the **first** result element of that response is used — no
disambiguation logic exists for multiple FDA matches on one candidate.

### The cache (`medicine_ndc_cache` table)

Keyed on `ndc11` (the raw 11-digit string, not a hyphenated NDC10 — a
natural single-column PK). One row per NDC, shared across all
pharmacies — FDA data is universal, not store-specific.

Stored columns (`models/medicine_ndc_cache.py`):

| Column | Used by |
|---|---|
| `brand_name`, `generic_name` | Module B fuzzy-match |
| `dosage_form`, `package_description` | Derives `is_unit_of_use` |
| `marketing_start_date`, `marketing_end_date` | Module A (raw `YYYYMMDD` strings, matching what the parser expects — not SQL `Date` columns) |
| `listing_expiration_date` | (fetched, not currently read by any Module A check — `marketing_end_date` is used for the "expires soon" comparison instead) |
| `is_unit_of_use` | Module C |
| `found_in_fda` | distinguishes "FDA confirmed not found" from "not yet looked up" |
| `raw_payload` | full FDA result JSON (`MEDIUMTEXT`) — forensics + backfill if new columns are added later |
| `fetched_at`, `updated_at` | TTL math (`updated_at` has `onupdate=now()`, and is what the TTL check compares against) |

### The actual lookup flow (`services/validation/ndc_cache.py::get_or_fetch`)

```
input: ndc11

1. row = SELECT * FROM medicine_ndc_cache WHERE ndc11 = ndc11   (PK get)
2. if row exists AND not force AND not NDC_CACHE_FORCE_REFRESH
      AND (now - row.updated_at) < TTL_DAYS:
     return row                      ← cache hit, ~0 ms, logged as "REFRESH" candidate skip
3. else:
     data = fetch_fda(ndc11)         ← tries up to 4 hyphenations, see above
     UPSERT medicine_ndc_cache (every column except ndc11 overwritten on conflict)
     commit                          ← commits INDEPENDENTLY of the caller's transaction, mid-request
     return the freshly-committed row
```

The function accepts a `force: bool` parameter, but **no current call
site ever passes `force=True`** — the only live way to bypass the cache
today is the global `settings.NDC_CACHE_FORCE_REFRESH` flag (restart
required, affects every lookup).

### Cache hit cases that surprise people

- **Cached "not found" still counts as a hit.** If `found_in_fda=False`
  is cached and not expired, FDA is *not* re-hit — otherwise sensors,
  lancets, and strips (which live in a different FDA database entirely)
  would burn 4 failed candidate lookups × 1.5s on every submission,
  forever.
- **Negative and positive TTL are the same** — 7 days
  (`NDC_CACHE_TTL_DAYS`) either way.
- Log lines read `NDC cache MISS` (no row existed at all) vs. `NDC cache
  REFRESH` (a stale row existed and was replaced) — useful for
  distinguishing "brand new NDC" from "cache just expired" when reading
  the dashboard log stream.

### When to invalidate

- Manually: `DELETE FROM medicine_ndc_cache WHERE ndc11 = '...'` — picked
  up on the next lookup.
- Automatically via the 7-day TTL.
- Globally via `NDC_CACHE_FORCE_REFRESH=true` in `.env` (restart
  required).
- There is currently no `GET/DELETE /admin/ndc-cache/{ndc11}` endpoint —
  cache maintenance is DB-console-only today.

---

## 7. How an `Alert` maps to the UI

```ts
interface Alert {
  module: "A"|"B"|"C"|"D"|"E"|"F"|"G"|"H"|"I"|"J"|"FIELD"|"INGEST"  // I/J/INGEST reserved, never emitted today
  code: string                       // stable machine identifier
  severity: "ERROR"|"WARNING"|"INFO"|"INDETERMINATE"|"PASS"
  message: string                    // human text
  medicine_index?: number            // which medicine row in the JSON
  dispense_index?: number            // which dispense inside that medicine
  ndc?: string
  rx_no?: string
  patient_key?: string               // never raw PHI
  field?: string                     // which field to highlight (drug_name / ndc / qty_disp / ...)
  expected?: any                     // for diff-style display — see the Module G gotcha in §3
  actual?: any
  suggestion?: string                // tooltip / inline help text
}
```

Suggested rendering rules:

| Severity | Color | Behavior |
|---|---|---|
| ERROR | red border + icon | scroll the medicine row into view, focus the `field`, disable Save |
| WARNING | amber border + icon | inline tooltip with `suggestion`, no save block |
| INFO | grey badge | aggregated in a side panel ("12 zero-refill rx, 8 unpaid lines") |
| INDETERMINATE | grey badge with `?` | tooltip: `PLAN_LOCKED` → "Upgrade to unlock this check"; `NDC_LOOKUP_FAILED` → "could not verify this NDC" |

`patient_key` is the right value for "show me everything wrong with this
patient" — group `alerts` by `patient_key` on the client to build the
per-patient drill-down view (the same key that
`GET /pharmacy/{ph_id}/refills` and `GET /pharmacy/{ph_id}/activity` use
elsewhere).

---

## 8. Insurance code canonicalisation (helper used by Modules F and G's grouping)

Source documents print the same plan under multiple spellings — column
bleed from an adjacent field, brand vs. legal-entity naming, truncation.
`services/validation/insurance_key.py::canonical_insurance(code)` folds
these to a single grouping key:

```python
def canonical_insurance(code: str | None) -> str | None:
    if not code:
        return None
    cleaned = WHITESPACE_RUN.sub(" ", code).strip().upper()
    if not cleaned:
        return None
    if cleaned in SYNONYMS:
        return SYNONYMS[cleaned]
    head = cleaned.split(" ", 1)[0]          # first whitespace-delimited token
    if head in SYNONYMS:
        return SYNONYMS[head]                 # strips trailing column-bleed, e.g. "MMS2084 7"
    return cleaned                            # unknown codes pass through as their own key, NOT None
```

### `SYNONYMS` table (exact, current)

| Raw (after uppercase + whitespace-collapse) | Canonical |
|---|---|
| `EMPIRE`, `EMPIREBCBS`, `EMPIRE BCBS` | `EMPIRE_BCBS` |
| `ANTHE`, `ANTHEM`, `ANTHEM BCBS` | `ANTHEM` |
| `AETMCR` | `AETNA_MCR` |
| `AETNA` | `AETNA` |
| `ES3`, `ESI` | `EXPRESS_SCRIPTS` |
| `MCD` | `MEDICAID` |
| `MMS205` | `MEDICAID_MMS205` |
| `MMS208`, `MMS2084` | `MEDICAID_MMS208` |
| `MMS2085` | `MEDICAID_MMS205` |
| `ADV` | `ADVANTAGE` |
| `AD1` | `ADVANTAGE_1` |
| `AD2` | `ADVANTAGE_2` |

**Read the `MMS2084`/`MMS2085` rows carefully** — they are *not* a
simple digit-suffix pattern (`MMS2084` doesn't map to `MMS208` by
symmetry with `MMS2085`→`MMS205`; both are hardcoded facts about how
this pharmacy's export actually mangles those two specific codes).
Don't infer a generalized rule from them when extending the table —
add new observed variants as their own explicit entries.

The **head-token fallback** (step 3 above) is what makes `"MMS2084 7"` —
where `"47"` is `Qty Ord` column-bleed appended to the insurance cell —
still resolve to `MEDICAID_MMS208`, because `"MMS2084 7".split(" ",
1)[0]` is `"MMS2084"`, which *is* a direct synonym key even though the
full cleaned string isn't.

Module F uses the canonical key for its `(patient_key, ndc,
canonical_insurance)` grouping, so a patient billed under `EMPIRE` for
one fill and `EMPIRE BCBS` for another is correctly flagged as the same
plan (a legitimate same-plan duplicate) instead of being silently
missed. The **raw** `ins_code` is preserved unchanged on the source
row — only the grouping key is canonicalized.

---

## 9. Configuration knobs (`core/config.py`)

```python
NDC_CACHE_TTL_DAYS            = 7      # how long before we re-verify a cached NDC
NDC_CACHE_FORCE_REFRESH       = False  # ops switch: bypass cache for every lookup (restart required)
DAYS_SUPPLY_RATE_MAX          = 50.0   # Module D (tier1) — qty/days above this → WARNING
DAYS_SUPPLY_RATE_MIN          = 0.05   # Module D (tier1) — qty/days below this → WARNING
NDC_LISTING_EXPIRY_INFO_DAYS  = 365    # Module A — INFO if end date is within this window
```

All can be overridden in `.env` without code changes. There is no knob
for the Module B name-overlap threshold (34%) or the Module A
"discontinued relative to dispense date vs. today" behavior — both are
hardcoded constants in `tier2.py`.

---

## 10. What's NOT in the engine yet (intentional)

| Missing | Why | When to add |
|---|---|---|
| Module I (missing prior-month refill) | Needs ≥ 1 prior period retained | Once we retain multiple reports per store |
| Module J (annual per-patient) | Needs 12 months + pickup/returned status | Same, + confirm a pickup field exists in the source data |
| RxNorm-based Module B | Spec recommends RxCUI mapping; current code uses FDA name fuzzy-match only | If the false-positive rate on `DRUG_NAME_MISMATCH` becomes a problem |
| SIG-based Module D (exact Tier 1) | Extractor doesn't capture SIG (directions) today | When the PDF/Excel pipeline starts extracting it |
| `GET/DELETE /admin/ndc-cache/{ndc11}` | Cache self-heals via TTL; no operator lever needed so far | When a stale FDA record causes a visible problem in production |
| `Alert.module` values `I`, `J`, `INGEST` | Reserved in the schema, no emitting code yet | Alongside the modules above |
| An independent `pack_size_billed_reconciliation`-style flag for tier2's `FRACTIONAL_DAILY_DOSE` check | Currently rides along transitively inside the A/B/C loop | If it needs to be sellable/gateable on its own |

Every genuinely "missing" capability is invisible to the user via a
`PLAN_LOCKED` or (for missing-history modules once built) an
`INDETERMINATE` "couldn't check, insufficient history" alert — never a
silent pass.

---

## 11. One-line summary of every alert code

| code | module | sev | what it means |
|---|---|---|---|
| `MALFORMED_NDC` | FIELD | ERROR | `ndc` is not 11 digits |
| `DRUG_NAME_BLEED` | FIELD | ERROR | extractor put column-label text into `drug_name`, or the name is implausibly long |
| `DUPLICATE_NDC_IN_REPORT` | FIELD | ERROR | same NDC in ≥2 medicine rows of one report |
| `MEDICINE_NO_DISPENSES` | FIELD | WARNING | medicine row has empty `dispenses[]` |
| `DAYS_SUPPLY_INVALID` | D | ERROR | `days_supply` missing or `≤ 0` |
| `DAYS_SUPPLY_RATE_OUT_OF_BOUNDS` | D | WARNING | qty/days outside `[DAYS_SUPPLY_RATE_MIN, DAYS_SUPPLY_RATE_MAX]` |
| `REPEAT_PATIENT_DRUG` | E | WARNING | same patient + NDC ≥ 2 in report |
| `REPEAT_PATIENT_DRUG_INSURANCE` | F | ERROR | same patient + NDC + canonical insurance ≥ 2 |
| `GRAND_TOTAL_DELTA_RX` | G | INFO | printed rx_count ≠ recomputed (see §3 field-naming gotcha) |
| `GRAND_TOTAL_DELTA_PRICE` | G | INFO | printed total_price ≠ recomputed sum |
| `UNPAID_LINE` | G | WARNING | price > 0 but ins_paid = 0 |
| `ZERO_REFILLS_REMAINING` | H | INFO | `ref` parses to `0` |
| `NDC_NOT_FOUND` | A | WARNING | NDC not in FDA Drug NDC Directory |
| `DRUG_DISPENSED_BEFORE_MARKETED` | A | WARNING | `date_filled` earlier than FDA `marketing_start_date` |
| `DRUG_DISPENSED_AFTER_DISCONTINUED` | A | ERROR | `date_filled` later than FDA `marketing_end_date` |
| `NDC_LISTING_EXPIRES_SOON` | A | INFO | FDA listing expires within `NDC_LISTING_EXPIRY_INFO_DAYS` |
| `NDC_LOOKUP_FAILED` | A | INDETERMINATE | FDA/cache lookup threw an exception |
| `DRUG_NAME_MISMATCH` | B | WARNING | printed name doesn't overlap FDA brand/generic by ≥34% |
| `UNIT_OF_USE_FRACTIONAL` | C | ERROR | unit-of-use product (inhaler/pen/kit/sensor/...) dispensed as a fractional quantity |
| `FRACTIONAL_DAILY_DOSE` | D (tier2) | WARNING | `qty_disp / days_supply` is not a whole number; transitively gated by A/B/C, not independently |
| `PLAN_LOCKED` | (any) | INDETERMINATE | the module was skipped because the store's plan doesn't grant its flag (see §12); doubles as an upsell prompt |

---

## 12. Subscription plan gating (`services/validation/plan_gate.py`)

Each module runs only if the store's **plan** grants its matching
feature flag (see `docs/plan_pricing.md` for pricing/positioning).
`validate_tier1`/`validate_tier2` both take `granted: set[str] | None` —
the store's `Plan.features` set; `None` means "run everything, no
gating" (used only by the Kafka Tier-1 preview and tests, never by an
HTTP-routed call). A skipped module emits exactly one `PLAN_LOCKED`
`INDETERMINATE` alert per module (never a silent pass).

| Module | Flag | Min plan |
|---|---|---|
| FIELD | *(none — always runs)* | any |
| E, F, H | `refill_analysis_billings` | Advanced |
| G | `top_quantity_drug_report` | Advanced |
| C | `pack_size_billed_reconciliation` | Advanced |
| D (tier1, days-supply) | `days_supply_validation` | Ultimate |
| A (discontinuation) | `discontinued_drug_detection` | Ultimate |
| B (NDC/claim mismatch) | `ndc_claim_mismatch_checks` | Ultimate |
| D (tier2, `FRACTIONAL_DAILY_DOSE`) | *(no direct flag — runs transitively whenever any of A/B/C's loop executes)* | n/a |

`insurance_ndc_analytics` (Advanced) exists in `core/enums.py::Feature`
and in `plan_gate.py`'s label table, but **no current `has(granted,
...)` call site references it** — it's reserved for a future module, not
wired to anything today.

**The FDA-lookup loop itself is only entered if at least one of A/B/C is
granted** — a store entitled to none of A/B/C makes zero FDA calls per
submission, saving the ~1–2s/NDC cost entirely, and still gets three
`PLAN_LOCKED` alerts (one per ungranted module among A/B/C) so the UI can
render an upsell.

`Plan.features`/`Plan.limits` (DB JSON columns, admin-editable at
runtime) are the actual source of truth for which plan grants which
flag — the labels in `plan_gate.py`'s `_FLAG_PLAN` table are for
building human-readable lock messages only, and are kept in sync with
`core/enums.py::Feature`'s own grouping comments, not the other way
around.
