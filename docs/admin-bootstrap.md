# QueueRx — Post-Deploy Admin Bootstrap

Run these **after `alembic upgrade head`** on the deployed host. All commands use
`curl` (works in PowerShell via `curl.exe` and in Git Bash). Replace the
placeholders at the top.

```bash
BASE_URL="https://YOUR_DEPLOY_HOST"      # e.g. http://localhost:5001
ADMIN_EMAIL="admin@yourco.com"
ADMIN_PASSWORD="YOUR_ADMIN_PASSWORD"
PHARMACY_ID="REPLACE_WITH_TEST_STORE_ID" # the store you want full access on
```

> The 3 plans are **auto-seeded by the migration** — step 2 just verifies them.
> Only run step 3 (POST /admin/plans) if `GET /plans` comes back empty.

---

## 1. Log in as ADMIN → capture the token

```bash
TOKEN=$(curl -s -X POST "$BASE_URL/user/login" \
  -H "Content-Type: application/json" \
  -d "{\"user_email\":\"$ADMIN_EMAIL\",\"input_password\":\"$ADMIN_PASSWORD\"}" \
  | python -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
echo "TOKEN=$TOKEN"
```

## 2. Verify the seeded plans + feature lists

```bash
curl -s "$BASE_URL/plans" -H "Authorization: Bearer $TOKEN" | python -m json.tool
```
Expect 3 plans (BASIC / ADVANCED / ULTIMATE) with these feature counts:
Basic = 7, Advanced = 14, Ultimate = 20.

## 3. (ONLY if plans are missing) Create them via admin API

<details><summary>POST bodies for all three plans</summary>

```bash
# BASIC — $29/mo
curl -s -X POST "$BASE_URL/admin/plans" -H "Authorization: Bearer $TOKEN" \
 -H "Content-Type: application/json" -d '{
  "code":"BASIC","name":"Basic","tier":1,"monthly_price_cents":2900,
  "limits":{"drug_reconciliation_limit":250},
  "features":["temp_monitoring_alerts","compliance_reports","inventory_lite",
    "invoice_upload_manual","expiration_lot_tracking","overstock_monitoring",
    "multi_location_access"]}'

# ADVANCED — $179/mo
curl -s -X POST "$BASE_URL/admin/plans" -H "Authorization: Bearer $TOKEN" \
 -H "Content-Type: application/json" -d '{
  "code":"ADVANCED","name":"Advanced","tier":2,"monthly_price_cents":17900,
  "limits":{"drug_reconciliation_limit":250},
  "features":["temp_monitoring_alerts","compliance_reports","inventory_lite",
    "invoice_upload_manual","expiration_lot_tracking","overstock_monitoring",
    "multi_location_access","invoice_to_inventory_auto","inventory_reconciliation_auto",
    "top_quantity_drug_report","insurance_ndc_analytics","pack_size_billed_reconciliation",
    "custom_patient_med_reports","refill_analysis_billings"]}'

# ULTIMATE — $349/mo (all features, unlimited)
curl -s -X POST "$BASE_URL/admin/plans" -H "Authorization: Bearer $TOKEN" \
 -H "Content-Type: application/json" -d '{
  "code":"ULTIMATE","name":"Ultimate","tier":3,"monthly_price_cents":34900,
  "limits":{},
  "features":["temp_monitoring_alerts","compliance_reports","inventory_lite",
    "invoice_upload_manual","expiration_lot_tracking","overstock_monitoring",
    "multi_location_access","invoice_to_inventory_auto","inventory_reconciliation_auto",
    "top_quantity_drug_report","insurance_ndc_analytics","pack_size_billed_reconciliation",
    "custom_patient_med_reports","refill_analysis_billings","ndc_claim_mismatch_checks",
    "days_supply_validation","discontinued_drug_detection","invoice_billed_cross_reconciliation",
    "annual_checkup_audit","early_access_features"]}'
```
</details>

---

## 4. Give the frontend test pharmacy FULL access (ULTIMATE, long expiry)

ULTIMATE grants all 20 features, so the frontend sees every gated route.
`current_period_end` is set far out so it won't expire during testing.

```bash
curl -s -X POST "$BASE_URL/admin/subscriptions" -H "Authorization: Bearer $TOKEN" \
 -H "Content-Type: application/json" -d "{
  \"medical_store_id\": $PHARMACY_ID,
  \"plan_code\": \"ULTIMATE\",
  \"status\": \"ACTIVE\",
  \"current_period_end\": \"2035-01-01T00:00:00\",
  \"notes\": \"Frontend test store — full access\"
}" | python -m json.tool
```

## 5. Confirm the test store's access

```bash
curl -s "$BASE_URL/subscription/$PHARMACY_ID" -H "Authorization: Bearer $TOKEN" | python -m json.tool
```
Expect `status: ACTIVE`, `plan.code: ULTIMATE`, `current_period_end: 2035-...`.

---

## Notes
- **Every other existing pharmacy has no subscription** → gated endpoints return
  **402** until you assign a plan the same way (step 4). That's expected (hard paywall).
- **Drug-count limit is disabled at launch** — the 250 value is stored on
  Basic/Advanced plans but not enforced yet (re-enable in `routes/dispense_save.py`).
- To change any plan's features later: `PUT /admin/plans/{plan_id}` with a new
  `features` list (no redeploy).
