# QueueRx — Plans & API Entitlements (as built · v2)

Aligned to **QueueRx Pricing Reference v2** (Basic / Advanced / Ultimate). This
describes how the backend actually enforces entitlements — flag keys, which API
endpoints each plan unlocks, and why.

- **Entitlement is per pharmacy** (`medical_store`), not per user.
- **Guard mechanism:** a gated route calls
  `ensure_feature(db, medical_store_id, Feature.X)` right after the ownership
  check. It reads the store's active subscription → the plan's `features` list
  (DB JSON, the source of truth) → returns **HTTP 402** if the subscription is
  missing/expired or the plan lacks that flag.
- **Flag keys** follow the v2 developer contract (snake_case). The `Feature`
  enum in `core/enums.py` holds all 20 boolean flags.
- **Expiry is lazy, no grace period.** Plans are **additive** (each tier
  includes everything below it).

---

## The three plans (seeded in migration `f7a8b9c0d1e2`)

| Plan | Code | Tier | Monthly | Drug reconciliation | Positioning |
|------|------|:---:|---:|---|---|
| Basic | `BASIC` | 1 | $29 | 250 | Compliance + inventory fundamentals |
| Advanced | `ADVANCED` | 2 | $179 | 250 | Basic + invoice automation + billing analytics |
| Ultimate | `ULTIMATE` | 3 | $349 | Unlimited | Full platform, unlimited dispensary intelligence |

> **Monthly billing only** (per the v2 sheet — no annual). Prices stored in
> **cents**; each subscription period is a fixed 30 days.
> The reconciliation cap lives in `Plan.limits` as
> `{"drug_reconciliation_limit": 250}` (Basic/Advanced) or `{}` (Ultimate = unlimited).

---

## Feature flags → min plan (v2 developer contract)

| Flag key | Min plan | Backing API endpoint(s)? |
|---|---|---|
| `temp_monitoring_alerts` | Basic | — (hardware device pipeline) |
| `compliance_reports` | Basic | ✅ audit report |
| `inventory_lite` | Basic | ✅ inventory + barcode |
| `invoice_upload_manual` | Basic | — (manual entry; no distinct endpoint) |
| `expiration_lot_tracking` | Basic | ✅ via inventory detail |
| `overstock_monitoring` | Basic | — (surfaced in inventory data) |
| `multi_location_access` | Basic | — (structural: `/pharmacy/*`) |
| `invoice_to_inventory_auto` | Advanced | ✅ invoice process/save/detail |
| `inventory_reconciliation_auto` | Advanced | — (not a separate endpoint yet) |
| `top_quantity_drug_report` | Advanced | ✅ dispense + reports |
| `insurance_ndc_analytics` | Advanced | — (part of report payload) |
| `pack_size_billed_reconciliation` | Advanced | — (part of validation) |
| `custom_patient_med_reports` | Advanced | — (report payload) |
| `refill_analysis_billings` | Advanced | ✅ refills |
| `ndc_claim_mismatch_checks` | Ultimate | ⚠️ inside validation engine (not separately gated) |
| `days_supply_validation` | Ultimate | ⚠️ inside validation engine (not separately gated) |
| `discontinued_drug_detection` | Ultimate | ⚠️ inside validation engine (not separately gated) |
| `invoice_billed_cross_reconciliation` | Ultimate | — (not built as endpoint yet) |
| `annual_checkup_audit` | Ultimate | — (not built yet) |
| `early_access_features` | Ultimate | — (product flag) |

✅ = enforced at an endpoint today · — = granted but no dedicated gated endpoint
· ⚠️ = computed but not yet separately gated (see gaps).

---

## Enforced endpoint → flag map (what the code checks today)

### `inventory_lite` *(Basic)*
Stock ledger + barcode-to-stock — the baseline every pharmacy needs.

| Method | Path |
|---|---|
| GET | `/pharmacy/{ph_id}/inventory` |
| GET | `/pharmacy/{ph_id}/inventory/{code}` |
| PATCH | `/pharmacy/{ph_id}/inventory/{code}` |
| POST | `/documents/process` *(process_type=`barcode`)* |

### `compliance_reports` *(Basic)*
| Method | Path |
|---|---|
| GET | `/pharmacy/{ph_id}/audit-report` |

### `invoice_to_inventory_auto` *(Advanced)*
Auto-convert a supplier invoice (PDF) into structured line items + stock.

| Method | Path |
|---|---|
| POST | `/documents/process` *(process_type=`invoice`)* |
| POST | `/invoices` |
| GET | `/invoices/{invoice_id}` |

### `top_quantity_drug_report` *(Advanced)*
Dispensed-drug reports and analytics.

| Method | Path |
|---|---|
| POST | `/documents/process` *(process_type=`dispense`)* |
| POST | `/dispenses/validate` |
| POST | `/dispenses` |
| GET | `/reports/{report_id}` |
| GET | `/reports/{report_id}/medicines/{ndc}` |
| DELETE | `/reports/{report_id}` |

### `refill_analysis_billings` *(Advanced)*
| Method | Path |
|---|---|
| GET | `/pharmacy/{ph_id}/refills` |
| DELETE | `/pharmacy/{ph_id}/refills/{patient_key}` |

---

## What each plan can call (cumulative)

| Endpoint group | Basic | Advanced | Ultimate |
|---|:---:|:---:|:---:|
| Inventory (list/detail/adjust, barcode) | ✅ | ✅ | ✅ |
| Audit / compliance report | ✅ | ✅ | ✅ |
| Invoice automation (upload/save/detail) | ❌ | ✅ | ✅ |
| Dispensary reports (dispense/reports) | ❌ | ✅ (≤250 drugs) | ✅ (unlimited) |
| Refill analysis | ❌ | ✅ | ✅ |

A call to a feature the plan doesn't include returns **402 Payment Required**.

---

## Not feature-gated (open to any authenticated user)
- **Auth & account:** `/user/*`
- **Pharmacy CRUD:** `/pharmacy/*` (multi-location is structural)
- **Activity feed:** `GET /pharmacy/{ph_id}/activity`
- **Document status:** `GET /documents/{doc_key}`, `GET /documents/`
- **Subscription self-service:** `GET /plans`, `GET /subscription/{store}`,
  `POST /subscription/subscribe`, `PUT /subscription/upgrade` *(owner or admin)*
- **Admin:** `/admin/subscriptions*`, `/admin/plans*` (ADMIN-only)

---

## Known gaps / open items (as built)

1. **🔴 Self-serve subscribe/upgrade grant plans for free.** No payment step, so
   an owner can `POST /subscription/subscribe` for `ULTIMATE` at $0. Treat these
   as admin-only / internal until billing lands.
2. **Ultimate-only validation checks aren't separately gated.**
   `ndc_claim_mismatch_checks`, `days_supply_validation`, and
   `discontinued_drug_detection` run *inside* the shared validation engine
   (`validate_tier1` / `validate_tier2`), reached via the Advanced-gated
   `/dispenses/validate` and `/dispenses`. So an **Advanced** store currently
   receives those Ultimate checks too. Enforcing them requires passing the plan
   into the validator and running the Ultimate checks conditionally.
3. **No ADMIN bypass** in `ensure_feature` — admins get 402 on unsubscribed
   stores (fails closed; likely unintended).
4. **Existing pharmacies need backfill** (hard-deny → 402 until assigned a plan).
5. **No payment gateway** — subscribe/upgrade/revoke are state-only, monthly only.

### Closed in this pass
- ✅ **Cross-store list endpoints gated:** `GET /invoices/` (→ `invoice_to_inventory_auto`)
  and `GET /reports/` (→ `top_quantity_drug_report`) now hide rows for non-entitled
  stores via `feature_gate.entitled_store_ids`. `GET /documents/*` stays
  status-only metadata (ungated by design).
- ✅ **`drug_reconciliation_limit` enforced** at `POST /dispenses` — a report with
  more drugs than the plan cap (250 on Basic/Advanced) is rejected with 402.
- ✅ **Micro-gated the validation engine** (`services/validation/plan_gate.py`):
  Ultimate-only checks — `days_supply_validation` (D), `discontinued_drug_detection`
  (A), `ndc_claim_mismatch_checks` (B) — now run **only on Ultimate**; Advanced gets
  a `PLAN_LOCKED` marker. Advanced keeps C/E/F/G/H. FDA lookups are skipped when no
  A/B/C flag is granted. See `docs/validation_engine.md` §12.
- ✅ **Built `invoice_billed_cross_reconciliation`** (Ultimate):
  `GET /pharmacy/{ph_id}/reconciliation/invoice-vs-billed` — per-NDC purchased-vs-
  billed-out comparison.

### Still not built (marked in the plan doc)
`temp_monitoring_alerts`, `invoice_upload_manual`, `inventory_reconciliation_auto`,
`custom_patient_med_reports`, `annual_checkup_audit`, `recalls` — flags exist in the
catalog but have no behavior yet. Pending LEAD answers on the plan doc's Q1–Q7
(esp. Module F tier + save-gate behavior for gated ERRORs).

---

## Admin & lifecycle controls
- **Assign / override:** `POST /admin/subscriptions`
- **Modify:** `PUT /admin/subscriptions/{id}` (plan / status / expiry)
- **Revoke:** `POST /admin/subscriptions/{id}/revoke`
- **Catalog:** `POST/PUT /admin/plans` — re-scope any tier's `features` without a
  redeploy (the flags are DB-stored).
- **Audit:** every change appends a `SubscriptionEvent`
  (`SUBSCRIBE`/`UPGRADE`/`DOWNGRADE`/`REVOKE`/`ADMIN_MODIFY`).
