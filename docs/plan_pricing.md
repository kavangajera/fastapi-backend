# QueueRx by PhaBO Labs

## Subscription Plans — Pricing & Feature Reference

QueueRx offers three subscription tiers:

- **Basic** — $29/month
- **Advanced** — $179/month
- **Ultimate** — $349/month

Each plan is **additive**, meaning every higher-tier plan includes all features from the lower tiers.

---

# Plan Overview

| Plan | Price | Positioning |
|------|------|-------------|
| **Basic** | **$29/mo** | Compliance and inventory fundamentals for a single or multi-location independent pharmacy. |
| **Advanced** | **$179/mo** | Everything in Basic, plus invoice automation and drug-level billing analytics (up to 250 drugs). |
| **Ultimate** | **$349/mo** | The complete platform with unlimited dispensary intelligence and advanced compliance safeguards. |

---

# Feature Comparison Matrix

| Feature | Basic | Advanced | Ultimate |
|---------|:-----:|:--------:|:--------:|
| Temperature monitoring & alerts | ✅ | ✅ | ✅ |
| Daily / Weekly / Monthly / Custom compliance reports | ✅ | ✅ | ✅ |
| Inventory Management Lite | ✅ | ✅ | ✅ |
| Invoice upload (photo/PDF/manual entry) | ✅ | ✅ | ✅ |
| Expiration & lot tracking, stock lookup | ✅ | ✅ | ✅ |
| Overstock monitoring | ✅ | ✅ | ✅ |
| Multiple-location access | ✅ | ✅ | ✅ |
| Invoice-to-Inventory auto-conversion (PDF/JPG) | — | ✅ | ✅ |
| Automated inventory reconciliation | — | ✅ | ✅ |
| Top-quantity drug reporting | — | ✅ | ✅ |
| Insurance / NDC analytics | — | ✅ | ✅ |
| Pack-size vs. billed quantity reconciliation | — | ✅ | ✅ |
| Custom patient medication reports | — | ✅ | ✅ |
| Refill analysis & allowed billings per patient | — | ✅ | ✅ |
| Drug reconciliation limit | 250 drugs | 250 drugs | Unlimited |
| NDC / claim mismatch checks | — | — | ✅ |
| Days-supply validations | — | — | ✅ |
| Discontinued billed-drug detection | — | — | ✅ |
| Invoice vs. billed inventory cross-reconciliation | — | — | ✅ |
| December annual "Checkup" compliance audit | — | — | ✅ |
| Early access to new features | — | — | ✅ |

---

# Plan Details

## Basic — $29/month

Includes:

- Temperature monitoring & alerts
- Daily, weekly, monthly, and custom compliance reports
- Inventory Management Lite
- Invoice upload (photo, PDF, or manual entry)
- Expiration & lot tracking
- Stock lookup
- Overstock monitoring
- Multiple-location access

---

## Advanced — $179/month

Everything in **Basic**, plus:

### Invoice to Inventory Automation

- PDF/JPG invoices automatically converted into inventory
- Automated inventory reconciliation

### Analytics & Reporting

- Top-quantity drug reporting (up to **250 drugs**)
  - Sort by quantity
  - Sort by insurance billed
- Insurance / NDC analytics
- Pack-size vs. billed quantity reconciliation
- Custom patient medication reports
- Refill analysis & allowed billings per patient

### Drug Reconciliation

- Up to **250 drugs** reconciled

---

## Ultimate — $349/month

Everything in **Advanced**, plus:

### Unlimited Intelligence

- Unlimited drug reconciliation
- Unlimited dispensary intelligence

### Advanced Compliance

- NDC / claim mismatch checks
- Days-supply validations
- Discontinued billed-drug detection
- Invoice vs. billed inventory cross-reconciliation

### Additional Benefits

- Temperature compliance
- Inventory automation
- Multiple-location access
- Overstock management
- December annual **"Checkup" Compliance Audit** (included free)
- Early access to new features

---

# Developer Reference — Feature Flags

| Feature | Suggested Flag Key | Minimum Plan |
|---------|--------------------|--------------|
| Temperature monitoring & alerts | `temp_monitoring_alerts` | Basic |
| Compliance reports | `compliance_reports` | Basic |
| Inventory Management Lite | `inventory_lite` | Basic |
| Invoice upload (manual entry) | `invoice_upload_manual` | Basic |
| Expiration & lot tracking / stock lookup | `expiration_lot_tracking` | Basic |
| Overstock monitoring | `overstock_monitoring` | Basic |
| Multiple-location access | `multi_location_access` | Basic |
| Invoice-to-Inventory auto-conversion | `invoice_to_inventory_auto` | Advanced |
| Automated inventory reconciliation | `inventory_reconciliation_auto` | Advanced |
| Top-quantity drug reporting | `top_quantity_drug_report` | Advanced |
| Insurance / NDC analytics | `insurance_ndc_analytics` | Advanced |
| Pack-size vs. billed reconciliation | `pack_size_billed_reconciliation` | Advanced |
| Custom patient medication reports | `custom_patient_med_reports` | Advanced |
| Refill analysis & allowed billings | `refill_analysis_billings` | Advanced |
| Drug reconciliation limit | `drug_reconciliation_limit` | Advanced |
| NDC / claim mismatch checks | `ndc_claim_mismatch_checks` | Ultimate |
| Days-supply validations | `days_supply_validation` | Ultimate |
| Discontinued billed-drug detection | `discontinued_drug_detection` | Ultimate |
| Invoice vs. billed cross-reconciliation | `invoice_billed_cross_reconciliation` | Ultimate |
| Annual "Checkup" compliance audit | `annual_checkup_audit` | Ultimate |
| Early access to new features | `early_access_features` | Ultimate |

---

## Notes

- **Minimum Plan** indicates the lowest subscription tier where a feature flag should evaluate to `true`.
- All higher subscription tiers automatically inherit the feature.
- `drug_reconciliation_limit` should be implemented as an **integer/enum** instead of a boolean:
  - `250` → Basic / Advanced
  - `unlimited` → Ultimate