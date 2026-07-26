# QueueRx — Route × Plan Access Matrix

Every route in the app and which plan can access it. Reflects the actual guards
in code (`ensure_feature`, `require_admin`, entitlement filters).

**Columns**
- **Free** = works with **no active subscription** (public or auth-only). Every
  free route is also available on all three paid plans.
- **Basic** ($29) · **Advanced** ($179) · **Ultimate** ($349) — the paid tiers.

**Cell legend**
- ✅ accessible
- ❌ blocked → **HTTP 402** (plan doesn't include the feature)
- ◐ callable, but **rows are filtered** to entitled stores (list endpoints return an empty list for non-entitled tiers)

**Route tags**
- 🔓 no authentication required
- 🛡️ requires **ADMIN** role (still no subscription needed)
- *(untagged)* = requires a valid Bearer token; per-route ownership rules apply

---

## System & Dashboard

| Route | Free | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|:--:|
| 🔓 `GET /` | ✅ | ✅ | ✅ | ✅ |
| 🔓 `GET /dashboard` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /api/monitor/overview` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /api/monitor/metrics` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /api/monitor/services` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /api/monitor/alerts` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /api/monitor/config` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /api/monitor/logs` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /api/monitor/documents/recent` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /api/monitor/documents/by-status` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /api/monitor/documents/by-type` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /api/monitor/documents/timeline` | ✅ | ✅ | ✅ | ✅ |

## Auth & Account

| Route | Free | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|:--:|
| 🔓 `POST /user/signup` | ✅ | ✅ | ✅ | ✅ |
| 🔓 `POST /user/verify-signup-otp` | ✅ | ✅ | ✅ | ✅ |
| 🔓 `POST /user/resend-signup-otp` | ✅ | ✅ | ✅ | ✅ |
| 🔓 `POST /user/login` | ✅ | ✅ | ✅ | ✅ |
| 🔓 `POST /app/login` | ✅ | ✅ | ✅ | ✅ |
| 🔓 `GET /user/renew-access-token` | ✅ | ✅ | ✅ | ✅ |
| `POST /user/logout` | ✅ | ✅ | ✅ | ✅ |
| `GET /user/me` | ✅ | ✅ | ✅ | ✅ |
| `PUT /user/update/me` | ✅ | ✅ | ✅ | ✅ |
| `DELETE /user/delete/me` | ✅ | ✅ | ✅ | ✅ |
| `PUT /user/update/{user_id}` | ✅ | ✅ | ✅ | ✅ |
| `DELETE /user/delete/{user_id}` | ✅ | ✅ | ✅ | ✅ |
| `POST /user/create-technician` | ✅ | ✅ | ✅ | ✅ |
| `POST /user/get-technician` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /user/all` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /user/by-email` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /user/by-role` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `POST /user/impersonate` | ✅ | ✅ | ✅ | ✅ |

## Pharmacy & Activity

| Route | Free | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|:--:|
| `POST /pharmacy/create-pharmacy` | ✅ | ✅ | ✅ | ✅ |
| `GET /pharmacy/get-pharmacy` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /pharmacy/get-pharmacy-by-owner` | ✅ | ✅ | ✅ | ✅ |
| `GET /pharmacy/by-name` | ✅ | ✅ | ✅ | ✅ |
| `PUT /pharmacy/update/{ph_id}` | ✅ | ✅ | ✅ | ✅ |
| `DELETE /pharmacy/delete/{ph_id}` | ✅ | ✅ | ✅ | ✅ |
| `GET /pharmacy/{ph_id}/activity` | ✅ | ✅ | ✅ | ✅ |

## Subscription & Plan management

| Route | Free | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|:--:|
| `GET /plans` | ✅ | ✅ | ✅ | ✅ |
| `GET /subscription/{medical_store_id}` | ✅ | ✅ | ✅ | ✅ |
| `POST /subscription/subscribe` | ✅ | ✅ | ✅ | ✅ |
| `PUT /subscription/upgrade` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `GET /admin/subscriptions` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `POST /admin/subscriptions` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `PUT /admin/subscriptions/{subscription_id}` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `POST /admin/subscriptions/{subscription_id}/revoke` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `POST /admin/plans` | ✅ | ✅ | ✅ | ✅ |
| 🛡️ `PUT /admin/plans/{plan_id}` | ✅ | ✅ | ✅ | ✅ |

## Documents (status/polling — not feature-gated)

| Route | Free | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|:--:|
| `GET /documents/{doc_key}` | ✅ | ✅ | ✅ | ✅ |
| `GET /documents/` | ✅ | ✅ | ✅ | ✅ |

---

# Feature-gated routes (require an active subscription)

## Inventory Lite — flag `inventory_lite` *(Basic+)*

| Route | Free | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|:--:|
| `GET /pharmacy/{ph_id}/inventory` | ❌ | ✅ | ✅ | ✅ |
| `GET /pharmacy/{ph_id}/inventory/{code}` | ❌ | ✅ | ✅ | ✅ |
| `PATCH /pharmacy/{ph_id}/inventory/{code}` | ❌ | ✅ | ✅ | ✅ |

## Compliance / Audit — flag `compliance_reports` *(Basic+)*

| Route | Free | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|:--:|
| `GET /pharmacy/{ph_id}/audit-report` | ❌ | ✅ | ✅ | ✅ |

## Document processing — flag depends on `process_type`

| Route | Free | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|:--:|
| `POST /documents/process` | ❌ | ◐¹ | ✅ | ✅ |

¹ **Basic** can process only `barcode` (→ `inventory_lite`). `invoice` needs
`invoice_to_inventory_auto` and `dispense` needs `top_quantity_drug_report`
(both Advanced+), so Basic is **❌** for those two `process_type`s.

## Invoice Automation — flag `invoice_to_inventory_auto` *(Advanced+)*

| Route | Free | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|:--:|
| `POST /invoices` | ❌ | ❌ | ✅ | ✅ |
| `GET /invoices/{invoice_id}` | ❌ | ❌ | ✅ | ✅ |
| `GET /invoices/` (list) | ◐ | ◐ | ✅ | ✅ |

## Dispensary Intelligence — flag `top_quantity_drug_report` *(Advanced+)*

| Route | Free | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|:--:|
| `POST /dispenses/validate` | ❌ | ❌ | ✅ | ✅ |
| `POST /dispenses` | ❌ | ❌ | ✅² | ✅ |
| `GET /reports/{report_id}` | ❌ | ❌ | ✅ | ✅ |
| `GET /reports/{report_id}/medicines/{ndc}` | ❌ | ❌ | ✅ | ✅ |
| `DELETE /reports/{report_id}` | ❌ | ❌ | ✅ | ✅ |
| `GET /reports/` (list) | ◐ | ◐ | ✅ | ✅ |

² **Advanced** is capped at **250 drugs per report** (`drug_reconciliation_limit`);
a report with more is rejected with 402. **Ultimate** is unlimited.

## Refill Analysis — flag `refill_analysis_billings` *(Advanced+)*

| Route | Free | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|:--:|
| `GET /pharmacy/{ph_id}/refills` | ❌ | ❌ | ✅ | ✅ |
| `DELETE /pharmacy/{ph_id}/refills/{patient_key}` | ❌ | ❌ | ✅ | ✅ |

## Invoice-vs-billed Reconciliation — flag `invoice_billed_cross_reconciliation` *(Ultimate)*

| Route | Free | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|:--:|
| `GET /pharmacy/{ph_id}/reconciliation/invoice-vs-billed` | ❌ | ❌ | ❌ | ✅ |

## Micro-gated validation checks (inside `POST /dispenses` + `/dispenses/validate`)

These aren't separate routes — they are **checks inside the dispense validation
engine**, gated per plan. A store reaches the dispense routes at Advanced+, then
the engine runs only the checks its plan grants (others return a `PLAN_LOCKED`
marker):

| Check (module) | Basic | Advanced | Ultimate |
|---|:--:|:--:|:--:|
| Field/data integrity (FIELD) | — | ✅ | ✅ |
| Billing totals, repeat/dup-claim, zero-refills (G/E/F/H) | — | ✅ | ✅ |
| Pack-size vs billed (C) | — | ✅ | ✅ |
| Days-supply validation (D) | — | 🔒 | ✅ |
| Discontinued-drug detection (A) | — | 🔒 | ✅ |
| NDC / claim mismatch (B) | — | 🔒 | ✅ |

🔒 = check is skipped and reported as `PLAN_LOCKED` (upgrade to run it).

---

## Summary

- **Free / no subscription:** all auth, account, pharmacy CRUD, activity,
  subscription self-service, admin, monitor, and document-status routes.
- **Basic+:** inventory + barcode processing + compliance/audit report.
- **Advanced+:** everything in Basic **plus** invoice automation, dispensary
  reports/analytics, and refill analysis (dispensary reports capped at 250 drugs).
- **Ultimate:** same routes as Advanced, but **no 250-drug cap** (and, once wired,
  the Ultimate-only validation checks — see `subscription-plans.md` gaps).

> Note: the paid tiers unlock the **same set of routes** as Advanced for
> Dispensary Intelligence — Ultimate's extra value today is the removed drug cap.
> The finer Ultimate-only validation flags run inside the shared validation
> engine and are not yet separately gated (documented gap).
