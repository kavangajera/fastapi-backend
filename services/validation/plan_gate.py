"""
services/validation/plan_gate.py
────────────────────────────────
Subscription micro-gating for the dispense validation engine.

Each validation module (A–H) maps to a feature flag from
``docs/plan_pricing.md``. The engine runs a module only if the store's plan
grants its flag; otherwise it emits a single ``PLAN_LOCKED`` INDETERMINATE
alert per skipped module — never a silent pass, and a built-in upsell.

``granted`` is the set of flag keys from ``Plan.features`` for the store's
active subscription. ``granted is None`` means "no subscription context"
(e.g. the Kafka worker's instant Tier-1 preview, or unit tests) → run
everything, preserving the engine's original behavior.

Defaults chosen while LEAD answers Q1–Q3 in the plan doc (documented here):
  - ``ndc_claim_mismatch_checks`` (Ultimate) maps to Module **B** only
    (NDC ↔ drug-name mismatch).
  - Module **F** (duplicate patient+drug+insurance claim) stays a base
    **Advanced** fraud check under ``refill_analysis_billings`` — Advanced
    keeps double-billing protection.
  - Gated save-blocking ERRORs (e.g. ``NDC_DISCONTINUED`` in Module A) are
    **skipped** for plans without the flag (pure paywall): the check simply
    doesn't run, so it can't block the save.
Revisit these once Q1–Q3 are answered.
"""

from __future__ import annotations

from schemas.validation import Alert

# Feature flag → the tier that first grants it (for user-facing lock messages).
_FLAG_PLAN: dict[str, str] = {
    "days_supply_validation": "Ultimate",
    "discontinued_drug_detection": "Ultimate",
    "ndc_claim_mismatch_checks": "Ultimate",
    "pack_size_billed_reconciliation": "Advanced",
    "top_quantity_drug_report": "Advanced",
    "insurance_ndc_analytics": "Advanced",
    "refill_analysis_billings": "Advanced",
}

# Human label per module for the lock message.
_MODULE_LABEL: dict[str, str] = {
    "A": "discontinued-drug detection",
    "B": "NDC / claim mismatch checks",
    "C": "pack-size vs billed reconciliation",
    "D": "days-supply validation",
    "E": "repeat patient + drug detection",
    "F": "duplicate-claim detection",
    "G": "billing totals & per-patient analytics",
    "H": "zero-refills worklist",
}


def has(granted: set[str] | None, flag: str) -> bool:
    """True if the check should run. ``granted is None`` → run everything."""
    return granted is None or flag in granted


def plan_locked_alert(module: str, flag: str) -> Alert:
    """A non-blocking marker that a module was skipped for the current plan."""
    plan = _FLAG_PLAN.get(flag, "a higher plan")
    label = _MODULE_LABEL.get(module, flag)
    return Alert(
        module=module,  # keeps the existing Module literal (A–H/FIELD)
        code="PLAN_LOCKED",
        severity="INDETERMINATE",
        message=f"{label} is not included in your current plan.",
        suggestion=f"Upgrade to {plan} to enable {label}.",
    )
