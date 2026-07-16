# Dispense Report Validation Engine

> Audience: backend devs maintaining the engine, and frontend devs
> binding alerts to the dispense edit UI.
> Companion to `Drug Dispensed Report Analysis Spec.docx` (§§ refs in
> parentheses point back to that spec).

---

## 1. What the engine does

When a dispense report (PDF / DOCX / XLS) is uploaded, the Kafka worker
extracts the structured JSON shown in `data` of the
`POST /documents/process` response. **No domain rows are persisted at
that point.** The validation engine then runs over that JSON and emits a
`ValidationReport` so the UI can show the user exactly what's wrong
*before* they press Save.

The engine runs in three places. They share the same Pydantic types so
the UI can write one renderer:

| Where | What runs | DB write? | Why |
|---|---|---|---|
| **`POST /documents/process` (dispense)** | **Tier 1** (pure data) | No | Surfaces alerts the instant extraction finishes — no waiting on FDA. |
| **`POST /dispenses/validate`** | **Tier 1 + Tier 2** (FDA) | No | UI live-feedback while the user edits the form. |
| **`POST /dispenses`** | **Tier 1 + Tier 2** | Yes — *unless* any ERROR-severity alert is present, in which case → 422, nothing written. | The save gate. |

The reason for two tiers: Tier 1 is instant, Tier 2 makes up to ~85 FDA
HTTP calls on a typical report (cached after the first lookup — see §6).

---

## 2. The report you got back

Your last `POST /documents/process` came back with this summary:

```json
"summary": {
  "errors": 4, "warnings": 8, "info": 0, "indeterminate": 0,
  "blocking": true, "tier1_ran": true, "tier2_ran": false
}
```

`blocking: true` means `POST /dispenses` would **refuse to save** this
body as-is. You'd have to fix the 4 ERRORs first.

The 4 errors and 8 warnings are explained module-by-module below.

---

## 3. Modules — every check in the engine

Each module emits zero or more `Alert` objects. Every alert carries
`module`, `code`, `severity`, plus enough location info
(`medicine_index`, `dispense_index`, `ndc`, `rx_no`, `field`) for the UI
to highlight the offending row/field.

### FIELD — sanity checks on the raw extracted data

These run first because every later module assumes the data shape is
sound.

| Code | Severity | Triggers when… | Where it fired in your report |
|---|---|---|---|
| `MALFORMED_NDC` | ERROR | `medicine.ndc` is not exactly 11 digits | — (every NDC was clean) |
| `DRUG_NAME_BLEED` | ERROR | The extractor smushed an adjacent column label (`Pres Addr`, `Pat Addr`, `Ins Paid`, `Qty Ord`, `Inventory Bucket`, etc.) into `drug_name`, OR `len(drug_name) > 80` | — (none on this run; spec §4.5 talks about this hazard) |
| `DUPLICATE_NDC_IN_REPORT` | **ERROR** | The same NDC appears in ≥ 2 medicine rows of one report (usually caused by name-bleed splitting one drug into multiple rows during extraction) | **4 hits** — `70377007713`, `51660052605`, `43547042309`, `00169418113`. Each of these NDCs appears twice — one row per date. |
| `MEDICINE_NO_DISPENSES` | WARNING | A medicine has zero dispenses attached | — |

**Why this is ERROR**: if `DUPLICATE_NDC` slipped past, the save route
would create two `Medicine` rows for the same product. Inventory
subtraction would then deduct twice (once per row), corrupting the
running stock for that NDC.

**Fix path**: merge the two medicine entries in the JSON — copy the
second row's `dispenses[]` array into the first row's `dispenses[]`,
delete the second row.

### D — qty / days_supply plausibility (Tier 1, §7.4)

| Code | Severity | Rule | Your data |
|---|---|---|---|
| `DAYS_SUPPLY_INVALID` | ERROR | `days_supply ≤ 0` or missing | — |
| `DAYS_SUPPLY_RATE_OUT_OF_BOUNDS` | WARNING | `qty_disp / days_supply` outside `[0.05, 50]` (configurable via `DAYS_SUPPLY_RATE_MIN/MAX`) | — |

**Why this rule is loose**: spec calls this "Tier 3" because we don't
have the SIG (directions). Tier 1 would be exact ("take 1 tab daily, 30
days, expect qty=30"); we can only catch obvious nonsense without the
SIG field. If the pharmacy starts exporting SIG, Module D upgrades to
Tier 1 automatically.

### E — same patient + same drug (Tier 1, §7.5)

| Code | Severity | Rule | Your data |
|---|---|---|---|
| `REPEAT_PATIENT_DRUG` | WARNING | `patient_key + ndc` appears ≥ 2 times in the report | — |

**Why warning, not error**: a legitimate refill on day N+30 is also the
same patient + same drug. Worth showing in a worklist, not an
auto-rejection.

### F — same patient + same drug + same insurance (Tier 1, §7.6)

| Code | Severity | Rule | Your data |
|---|---|---|---|
| `REPEAT_PATIENT_DRUG_INSURANCE` | **ERROR** | `patient_key + ndc + canonical_insurance` ≥ 2 times | — |

**Why this is the strongest fraud signal**: same patient + same drug +
same plan on the same day is almost always a billing duplicate. Spec
calls F "the single strongest signal for plan-level double-billing."
Insurance codes are canonicalised first (see §8) so `EMPIRE` and
`EMPIRE BCBS` count as the same plan.

### G — billing reconciliation + per-patient + unpaid (Tier 1, §7.7)

Module G emits *three* kinds of output:

1. **Grand-total recompute**. Independently sums every dispense's price,
   ins_paid, qty, and rx_count, then compares against the printed
   `grand_total.*`. Discrepancies surface as INFO alerts:

   | Code | Severity | Rule |
   |---|---|---|
   | `GRAND_TOTAL_DELTA_RX` | INFO | printed `total_rx_count` ≠ recomputed |
   | `GRAND_TOTAL_DELTA_PRICE` | INFO | printed `total_price` ≠ recomputed |

   In your run both deltas were `0` — the extractor matched the printed
   totals exactly this time. (Spec §4.4 warns that printed totals are
   frequently corrupted; always trust the recomputed value.)

2. **Per-patient totals**. Every patient grouped by `patient_key`, sorted
   by total billed. Used to render report **R3** ("Per-patient billing
   summary"). Your top spenders:

   ```
   ESPOSITO, F.   1 rx  $4471.68
   HORSFORD, E.   2 rx  $3740.22
   GITTENS, L.    6 rx  $2919.54
   ```

3. **Unpaid lines** (`price > 0 but ins_paid == 0`):

   | Code | Severity | Rule | Your data |
   |---|---|---|---|
   | `UNPAID_LINE` | WARNING | The price was charged but insurance paid nothing | **8 hits** — JOSEPH (BROMPHENIRAMINE), HANSEN (3 different drugs on plan `MMS20847`), ISAAC (VIT D), HODENFIELD (MELOXICAM), ROSENFELD (ROSUVASTATIN), GORDON (TRIAMCINOLONE) |

   This is the right severity: warning, not error. Possible reasons are
   cash sale, claim rejection, or coupon override — the engine can't
   distinguish those without more data, so it surfaces them all for
   human review.

### H — refills remaining = 0 (Tier 1, §7.8)

| Code | Severity | Rule |
|---|---|---|
| `ZERO_REFILLS_REMAINING` | INFO | `ref == 0` for that dispense |

Used to render report **R4** (zero-refill worklist) — every patient who
needs a new prescription before their next pickup.

> **Important**: in the response you posted, this module shows `0` info
> alerts even though dozens of dispenses have `ref: "0.0"`. That was a
> bug — the parser called `int("0.0")` which raises `ValueError`. Fixed
> just now in `tier1.py::_check_zero_refills` and `_to_int` to also
> accept float-stringified ints. Re-uploading the same PDF will now show
> ~30 INFO `ZERO_REFILLS_REMAINING` alerts.

### A — NDC validity / discontinuation (Tier 2, §7.1)

This is where FDA gets called. Per NDC, one of:

| Code | Severity | Rule |
|---|---|---|
| `NDC_DISCONTINUED` | ERROR | `marketing_end_date < today` |
| `NDC_NOT_FOUND` | WARNING | NDC not present in the FDA Drug NDC Directory (often a medical device — sensors, strips, lancets — that live in the FDA Device DB, or a very recent launch) |
| `NDC_LISTING_EXPIRES_SOON` | INFO | `end_date - today < NDC_LISTING_EXPIRY_INFO_DAYS` (default 365) |
| (none) | PASS | currently marketed, end date > 1 year away |

Not in your current report because the response shows
`tier2_ran: false`. To see these, hit `POST /dispenses/validate` with
the same body — that runs Tier 2.

### B — drug_name ↔ NDC consistency (Tier 2, §7.2)

| Code | Severity | Rule |
|---|---|---|
| `DRUG_NAME_MISMATCH` | WARNING | The printed `drug_name`'s significant tokens don't overlap with the FDA `brand_name` or `generic_name` for that NDC by at least 34 % |

Catches "this NDC really is something else" — e.g. wrong NDC typed in
for the drug name shown. Brand-vs-generic is still a match (e.g.
*Lipitor* ↔ *Atorvastatin*) because FDA's `generic_name` carries both
sides.

### C — package size vs dispensed quantity (Tier 2, §7.3)

| Code | Severity | Rule |
|---|---|---|
| `UNIT_OF_USE_FRACTIONAL` | **ERROR** | The FDA cache flagged the product as "unit-of-use" (inhaler / pen / kit / sensor / strip / lancet / prefilled syringe / auto-injector) AND a dispense's `qty_disp` is not a whole number |

For your data this will fire on `BREZTRI` (qty 32.1, inhaler) and
probably `SYMBICORT` (10.2, inhaler).

### Modules I and J — deferred

Need historical data we don't yet retain (prior month for I, 12 months
for J). Once you start saving multiple reports, these will start
emitting from the same engine entry-point with no new code.

---

## 4. Severity → what the UI should do

| Severity | UI treatment | Save behavior |
|---|---|---|
| `ERROR` | Red. Highlight the field. Disable Save until fixed. | `POST /dispenses` returns 422 with the full `ValidationReport` in `detail.data`. |
| `WARNING` | Amber. Soft callout — "verify this". | Save still succeeds. Alert returned in `DispenseSaveResponse.validation`. |
| `INFO` | Grey. Worklist entry, no action prompt. | Same as WARNING. |
| `INDETERMINATE` | Grey + "couldn't check" badge. | Same as WARNING. |
| `PASS` | Engine doesn't emit these as alerts; they're implicit. | n/a. |

`summary.blocking = (errors > 0)`. If false, Save proceeds; if true,
422.

---

## 5. `patient_key` — what it is and why it exists

Look at any UNPAID_LINE alert in your response:

```json
{
  "code": "UNPAID_LINE",
  "rx_no": "505715.0",
  "ndc": "69097007212",
  "patient_key": null
}
```

…then look at the `per_patient` array:

```json
{
  "patient_key": "2f7d994fb191d02d",
  "patient_label": "DUPONT HERARD, M.",
  "rx_count": 8,
  "total_price": "60.14"
}
```

That 16-char hex string is a **stable per-patient identifier** computed
deterministically from the dispense row, **without storing the patient's
name, phone, or full address** in any alert payload, log line, or DB row.

### How it's computed (`services/validation/patient_key.py`)

```python
patient_key = sha1(
    upper(strip(pat_name))           # "DUPONT HERARD, MARIE"
    + "|"
    + digits_only(pat_phone)         # "3478585259"
    + "|"
    + first_zip5(pat_addr)           # "11214" (extracted from "...NY 11214")
).hexdigest()[:16]
```

So `("DUPONT HERARD, MARIE", "3478585259", addr containing "11214")`
always produces `2f7d994fb191d02d`, regardless of which dispense row
that combination appears in.

### Why this design

1. **Group dispenses across rows reliably.** Spec §6.3 says the same
   person can appear under several `rx_no`s, sometimes with slightly
   different name formatting (`DUPONT HERARD, MARIE` vs `HERARD,
   MARIE`). Modules E, F, G all need a stable key to group on. NDC and
   `rx_no` aren't enough — Rx number is per-prescription not per-patient.
2. **PHI safety** (spec §13). The alert payload and the dashboard log
   stream are visible to backend operators / Claude Code agents / log
   collectors who shouldn't see raw patient names. The hash is one-way
   — given just the key you can't recover the name.
3. **The UI still gets a human-readable label.** `patient_label`
   (`"DUPONT HERARD, M."`) is computed separately — last name + first
   initial only. Enough for the operator to recognize the row;
   structurally less than what was already on the screen.

### Where it appears

- On every alert involving a dispense (`Alert.patient_key`).
- On every `per_patient` entry (used to render report R3).
- In the log line if we ever log alerts: `patient_key=<hex>` only,
  never `pat_name=`.

### What about the same patient under different name spellings?

Bad case: PDF page 1 prints `HERARD, MARIE`, page 2 prints
`DUPONT HERARD, MARIE`. Same person, different `normalize_name()`
output → two `patient_key`s. The phone + ZIP5 components limit this
("phone matches but name differs" can be addressed later by adding a
phone+zip5 fallback grouping). Spec §6.3 calls out that the stakeholder
needs to provide a stable patient ID if name-disambiguation false
negatives become a problem; until then this hash is the best we can do
from the data the report carries.

---

## 6. FDA call lifecycle — when, why, and the cache

### When the call happens

- **`POST /documents/process` (dispense)** → **no** FDA call.
- **`POST /dispenses/validate`** → first time for a given NDC, **yes**.
  Subsequent calls within `NDC_CACHE_TTL_DAYS` (default 7) → cache hit.
- **`POST /dispenses`** → same: cache first, FDA on miss.
- **`POST /documents/process` (barcode)** → still hits FDA from the
  barcode worker (separate path; not gated by this cache).

### Why two-tier (and not always-run-FDA)

Each FDA call takes **1–2 seconds** because the `api.fda.gov/drug/ndc.json`
endpoint expects an NDC10 in one of three hyphenated forms — we try up
to 4 candidates before giving up. ~85 medicines × 1.5 s = **~2 min of
HTTP** on a cold submit. We can't put that in the upload path
(`PROCESSING_RESULT_TIMEOUT_SECONDS = 180` would be borderline). So
Tier 1 runs inline (instant), Tier 2 runs on demand.

### The cache (`medicine_ndc_cache` table)

Keyed on `ndc11` (natural PK). One row per NDC, shared across all
pharmacies — FDA data is universal, not store-specific.

Stored columns (`models/medicine_ndc_cache.py`):

| Column | Used by |
|---|---|
| `brand_name`, `generic_name` | Module B fuzzy-match |
| `dosage_form`, `package_description` | Derives `is_unit_of_use` |
| `marketing_end_date`, `listing_expiration_date` | Module A discontinued / expires-soon |
| `is_unit_of_use` | Module C |
| `found_in_fda` | distinguishes "FDA confirmed NOT_FOUND" from "never looked up" |
| `raw_payload` | full FDA result dict — forensics + backfill if we add new columns later |
| `fetched_at`, `updated_at` | TTL math |

### The actual lookup flow (`services/validation/ndc_cache.py::get_or_fetch`)

```
input: ndc11

1. SELECT * FROM medicine_ndc_cache WHERE ndc11 = ?
2. if row exists AND (now - row.updated_at) < TTL:
     return row     ← cache hit; ~0 ms
3. else:
     for cand in ndc11_to_ndc10_candidates(ndc11):     # up to 4 hyphenations
         resp = GET api.fda.gov/drug/ndc.json?search=packaging.package_ndc:"<cand>"
         if 200 + results:
             break
     row = normalize(resp)   # extracts brand/generic/end_date/is_unit_of_use/...
     INSERT ... ON DUPLICATE KEY UPDATE   # MySQL upsert; safe under concurrency
     return row     ← cache miss; 1–6 s
```

### Cache hit cases that surprise people

- **Cached NOT_FOUND**. If `found_in_fda = False` is in cache and not
  expired, we still skip FDA. Otherwise sensors / lancets / strips would
  waste 4 retries × 1.5 s per submit forever.
- **Negative cache TTL is the same**. 7 days for both hits and misses.
  Set `NDC_CACHE_FORCE_REFRESH=true` in `.env` (and restart) for one
  run if you want to ignore the cache entirely.

### What you'll see if you re-run the FDA-dependent endpoints

Hit `POST /dispenses/validate` with the body you have. First time:
~30-60 s. The dashboard log stream will show one `NDC cache MISS` line
per medicine. Second time (anywhere on this report or any other dispense
with the same NDCs): under a second.

### When to invalidate

- Manually, by deleting a row (`DELETE FROM medicine_ndc_cache WHERE
  ndc11 = '...'`). Will be picked up on the next lookup.
- Automatically via TTL (7 days).
- Globally via `NDC_CACHE_FORCE_REFRESH=true` in `.env`.

Future: add `GET/DELETE /admin/ndc-cache/{ndc11}` for ADMIN role —
useful for "FDA updated their record, refresh now" without restart.

---

## 7. How an `Alert` maps to the UI

```ts
interface Alert {
  module: "A"|"B"|"C"|"D"|"E"|"F"|"G"|"H"|"FIELD"|"INGEST"
  code: string                       // stable machine identifier
  severity: "ERROR"|"WARNING"|"INFO"|"INDETERMINATE"|"PASS"
  message: string                    // human text
  medicine_index?: number            // which medicine row in the JSON
  dispense_index?: number            // which dispense inside that medicine
  ndc?: string
  rx_no?: string
  patient_key?: string               // never raw PHI
  field?: string                     // which field to highlight (drug_name / ndc / qty_disp / ...)
  expected?: any                     // for diff-style display
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
| INDETERMINATE | grey badge with `?` | tooltip says "could not verify this NDC" |

`patient_key` is the right value to use for "show me everything wrong
with this patient" — group `alerts` by `patient_key` on the client to
build the per-patient drill-down view.

---

## 8. Insurance code canonicalisation (helper used by F and G)

In your data the same plan appears as:

- `MMS208` (clean)
- `MMS20847` (with a stray `47` — that's column bleed of the `Qty Ord`
  value into the `Ins Code` cell, spec §4.5)
- `EMPIRE`
- `EMPIREBCBS`
- `ANTHE` (truncated `ANTHEM BCBS`)
- `MCD` (Medicaid)

`services/validation/insurance_key.py::canonical_insurance()` folds
these to a single key:

```
MMS208     → MEDICAID_MMS208
MMS20847   → MEDICAID_MMS208  (first token wins)
MMS2084 7  → MEDICAID_MMS208
EMPIRE     → EMPIRE_BCBS
EMPIREBCBS → EMPIRE_BCBS
ANTHE      → ANTHEM
ANTHEM BCBS→ ANTHEM
MCD        → MEDICAID
```

Module F uses the canonical key so a patient billed under `EMPIRE` for
one fill and `EMPIRE BCBS` for another is flagged as the same plan
(legitimate same-plan duplicate), instead of being silently missed.

Raw `ins_code` is still preserved on the row — only the *grouping key*
is canonical.

---

## 9. Configuration knobs (`core/config.py`)

```python
NDC_CACHE_TTL_DAYS         = 7        # how long before we re-verify a cached NDC
NDC_CACHE_FORCE_REFRESH    = False    # ops switch: bypass cache for one run
DAYS_SUPPLY_RATE_MAX       = 50.0     # Module D — qty/days above this → WARNING
DAYS_SUPPLY_RATE_MIN       = 0.05     # Module D — qty/days below this → WARNING
NDC_LISTING_EXPIRY_INFO_DAYS = 365    # Module A — INFO if end date is within this window
```

All can be overridden in `.env` without code changes.

---

## 10. What's NOT in the engine yet (intentional)

| Missing | Why | When to add |
|---|---|---|
| Module I (missing prior-month refill) | Needs ≥ 1 prior period | Once we retain multiple reports per store |
| Module J (annual per-patient) | Needs 12 months + pickup/returned status | Same + stakeholder confirms pickup field exists |
| RxNorm-based Module B | Spec recommends RxCUI mapping; we use FDA fuzzy match only | If false-positive rate becomes a problem |
| SIG-based Module D (Tier 1 exact) | Extractor doesn't capture SIG today | When PDF pipeline starts extracting it |
| `GET /admin/ndc-cache/...` | Cache works without operator intervention so far | When a stale FDA record bites in production |

Every "missing" item is invisible to the user via `INDETERMINATE`
alerts ("couldn't check, insufficient history") — never a silent pass.

---

## 11. One-line summary of every alert code

| code | module | sev | what it means |
|---|---|---|---|
| `MALFORMED_NDC` | FIELD | ERROR | `ndc` is not 11 digits |
| `DRUG_NAME_BLEED` | FIELD | ERROR | extractor put column-label text into `drug_name` |
| `DUPLICATE_NDC_IN_REPORT` | FIELD | ERROR | same NDC in ≥2 medicine rows of one report |
| `MEDICINE_NO_DISPENSES` | FIELD | WARNING | medicine row has empty `dispenses[]` |
| `DAYS_SUPPLY_INVALID` | D | ERROR | `days_supply ≤ 0` |
| `DAYS_SUPPLY_RATE_OUT_OF_BOUNDS` | D | WARNING | qty/days outside generic bounds |
| `REPEAT_PATIENT_DRUG` | E | WARNING | same patient + NDC ≥ 2 in report |
| `REPEAT_PATIENT_DRUG_INSURANCE` | F | ERROR | same patient + NDC + canonical insurance ≥ 2 |
| `GRAND_TOTAL_DELTA_RX` | G | INFO | printed rx_count ≠ recomputed |
| `GRAND_TOTAL_DELTA_PRICE` | G | INFO | printed total_price ≠ recomputed |
| `UNPAID_LINE` | G | WARNING | price > 0 but ins_paid = 0 |
| `ZERO_REFILLS_REMAINING` | H | INFO | `ref == 0` |
| `NDC_DISCONTINUED` | A | ERROR | FDA `marketing_end_date < today` |
| `NDC_NOT_FOUND` | A | WARNING | NDC not in FDA Drug NDC Directory |
| `NDC_LISTING_EXPIRES_SOON` | A | INFO | FDA listing expires within `NDC_LISTING_EXPIRY_INFO_DAYS` |
| `NDC_LOOKUP_FAILED` | A | INDETERMINATE | FDA/cache lookup threw |
| `DRUG_NAME_MISMATCH` | B | WARNING | printed name doesn't overlap FDA brand/generic |
| `UNIT_OF_USE_FRACTIONAL` | C | ERROR | inhaler/pen/kit/sensor dispensed as fractional qty |
| `PLAN_LOCKED` | (any) | INDETERMINATE | the module was skipped because the store's plan doesn't include it (see §12) |

---

## 12. Subscription micro-gating (`services/validation/plan_gate.py`)

The engine runs each module only if the store's **plan** grants the matching
feature flag (`docs/plan_pricing.md`). `validate_tier1` / `validate_tier2` take a
`granted: set[str] | None` (the store's `Plan.features`; `None` = run all, used
by the Kafka preview and tests). A skipped module emits one `PLAN_LOCKED`
INDETERMINATE alert (never a silent pass; doubles as an upsell).

| Module | Flag | Min plan |
|---|---|---|
| FIELD | *always* (data integrity — protects inventory math) | any |
| G (totals/per-patient), E/F (repeat/dup-claim), H (zero-refills) | `top_quantity_drug_report` / `refill_analysis_billings` | Advanced |
| C (pack-size) | `pack_size_billed_reconciliation` | Advanced |
| D (days-supply) | `days_supply_validation` | Ultimate |
| A (discontinued) | `discontinued_drug_detection` | Ultimate |
| B (NDC/claim mismatch) | `ndc_claim_mismatch_checks` | Ultimate |

When no A/B/C flag is granted, the FDA lookup is skipped entirely (saves
~1–2 s/NDC). Defaults pending LEAD sign-off (see the plan doc Q1–Q3): Module F
stays Advanced; gated save-blocking ERRORs (e.g. `NDC_DISCONTINUED`) are skipped
for plans without the flag (pure paywall).
