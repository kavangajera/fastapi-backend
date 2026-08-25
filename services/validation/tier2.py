"""
services/validation/tier2.py
────────────────────────────
FDA-dependent checks. Uses `services.validation.ndc_cache.get_or_fetch`
so per-NDC FDA calls happen at most once per TTL window.

Modules:
    A  NDC validity / discontinuation
       - row not in FDA Drug NDC Directory             → WARNING NDC_NOT_FOUND
       - marketing_end_date < today                    → ERROR  NDC_DISCONTINUED
       - end_date within NDC_LISTING_EXPIRY_INFO_DAYS  → INFO   NDC_LISTING_EXPIRES_SOON
       - else                                          → PASS (no alert)

    B  drug_name ↔ NDC
       Fuzzy token-overlap (≥ 34 %) between printed drug_name and
       FDA brand_name OR generic_name. No match → WARNING.

    C  package size vs quantity
       cache.is_unit_of_use AND any dispense qty_disp is not a whole
       number → ERROR. Otherwise INFO (bulk) or PASS (whole multiples).

Combinator modules (sums, repeat counts) live in tier1.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.medicine_inventory import MedicineInventory
from schemas.validation import Alert, ValidationReport
from services.validation.ndc_cache import get_or_fetch
from services.validation.plan_gate import has, plan_locked_alert
from services.validation.severity import summarize


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _parse_yyyymmdd(s: str | None) -> date | None:
    if not s or len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _name_tokens(s: str | None) -> set[str]:
    return {
        w for w in re.findall(r"[A-Z0-9]+", (s or "").upper()) if len(w) > 2 and not w.isdigit()
    }


def _name_overlap(label: str | None, *fda_names: str | None) -> tuple[bool, str | None]:
    lw = _name_tokens(label)
    if not lw:
        return False, None
    for cand in fda_names:
        cw = _name_tokens(cand)
        if cw and len(lw & cw) / max(1, len(cw)) >= 0.34:
            return True, cand
    return False, fda_names[0] if fda_names else None


# ─────────────────────────────────────────────────────────────────────



def _parse_dispense_date(d_str: str | None) -> date | None:
    if not d_str:
        return None
    import dateutil.parser
    try:
        return dateutil.parser.parse(d_str).date()
    except Exception:
        return None

def _module_a(
    mi: int, ndc11: str, med: dict, cache_row, today: date, alerts: list[Alert], strict_date_check: bool = True
) -> None:
    if cache_row is None or not cache_row.found_in_fda:
        alerts.append(
            Alert(
                module="A",
                code="NDC_NOT_FOUND",
                severity="WARNING",
                message=(
                    "NDC not present in FDA Drug NDC Directory — a discontinued/delisted product"
                ),
                medicine_index=mi,
                ndc=ndc11,
                actual=med.get("drug_name", ""),
                suggestion="Verify NDC manually; devices live in the FDA Device DB, not Drug.",
            )
        )
        return

    start_dt = _parse_yyyymmdd(cache_row.marketing_start_date)
    end_dt = _parse_yyyymmdd(cache_row.marketing_end_date)
    
    for di, disp in enumerate(med.get("dispenses", [])):
        date_filled_str = disp.get("date_filled")
        dispense_dt = _parse_dispense_date(date_filled_str)
        
        # Handle missing dates
        if not dispense_dt:
            if not strict_date_check:
                continue
            dispense_dt = today
            
        if start_dt and dispense_dt < start_dt:
            alerts.append(
                Alert(
                    module="A",
                    code="DRUG_DISPENSED_BEFORE_MARKETED",
                    severity="WARNING",
                    message=(
                        f"Dispensed on {dispense_dt.isoformat()} but FDA marketing start date is {start_dt.isoformat()}."
                    ),
                    medicine_index=mi,
                    dispense_index=di,
                    ndc=ndc11,
                    actual=date_filled_str or "Missing (Used Upload Date)",
                    suggestion="Verify dispense date.",
                )
            )
            
        if end_dt and dispense_dt > end_dt:
            alerts.append(
                Alert(
                    module="A",
                    code="DRUG_DISPENSED_AFTER_DISCONTINUED",
                    severity="ERROR",
                    message=(
                        f"Dispensed on {dispense_dt.isoformat()} but FDA marketing end date is {end_dt.isoformat()}."
                    ),
                    medicine_index=mi,
                    dispense_index=di,
                    ndc=ndc11,
                    actual=date_filled_str or "Missing (Used Upload Date)",
                    suggestion="Remove from active inventory.",
                )
            )

    if end_dt:
        delta = (end_dt - today).days
        if 0 <= delta < settings.NDC_LISTING_EXPIRY_INFO_DAYS:
            alerts.append(
                Alert(
                    module="A",
                    code="NDC_LISTING_EXPIRES_SOON",
                    severity="INFO",
                    message=(
                        f"Listing expires {end_dt.isoformat()} ({delta} days). "
                    ),
                    medicine_index=mi,
                    ndc=ndc11,
                    actual=cache_row.marketing_end_date,
                )
            )


def _module_b(mi: int, ndc11: str, drug_name: str, cache_row, alerts: list[Alert]) -> None:
    if cache_row is None or not cache_row.found_in_fda:
        return  # A already raised NOT_FOUND
    ok, matched = _name_overlap(drug_name, cache_row.brand_name, cache_row.generic_name)
    if not ok:
        alerts.append(
            Alert(
                module="B",
                code="DRUG_NAME_MISMATCH",
                severity="WARNING",
                message=(
                    f"Printed drug name '{drug_name}' does not match the FDA "
                    f"product for this NDC (brand='{cache_row.brand_name}', "
                    f"generic='{cache_row.generic_name}')."
                ),
                medicine_index=mi,
                ndc=ndc11,
                field="drug_name",
                actual=drug_name,
                expected=matched,
                suggestion="Confirm the NDC matches the product actually dispensed.",
            )
        )


def _module_c(mi: int, ndc11: str, med: dict, cache_row, alerts: list[Alert]) -> None:
    if cache_row is None or not cache_row.found_in_fda:
        return  # nothing to compare against
    if not cache_row.is_unit_of_use:
        return  # bulk-dispensed: no flag
    for di, disp in enumerate(med.get("dispenses", [])):
        qty = _to_decimal(disp.get("qty_disp"))
        if qty is None:
            continue
        if qty != qty.to_integral_value():
            alerts.append(
                Alert(
                    module="C",
                    code="UNIT_OF_USE_FRACTIONAL",
                    severity="ERROR",
                    message=(
                        f"{cache_row.dosage_form or 'Unit-of-use product'} must "
                        f"dispense whole multiples; got qty_disp={qty}."
                    ),
                    medicine_index=mi,
                    dispense_index=di,
                    ndc=ndc11,
                    rx_no=disp.get("rx_no"),
                    field="qty_disp",
                    actual=str(qty),
                    suggestion="Set qty_disp to a whole number of packages/units.",
                )
            )


# ─────────────────────────────────────────────────────────────────────



def _module_d(mi: int, ndc11: str, med: dict, alerts: list[Alert]) -> None:
    for di, disp in enumerate(med.get("dispenses", [])):
        qty_str = disp.get("qty_disp")
        days_str = disp.get("days_supply")
        if qty_str is None or days_str is None or str(qty_str).strip() == "" or str(days_str).strip() == "":
            continue
        
        qty = _to_decimal(qty_str)
        days = _to_decimal(days_str)
        
        if qty is None or days is None or days == 0:
            continue
            
        ratio = qty / days
        if ratio != ratio.to_integral_value():
            alerts.append(
                Alert(
                    module="D",
                    code="FRACTIONAL_DAILY_DOSE",
                    severity="WARNING",
                    message=f"qty_disp / days_supply ({qty} / {days} = {ratio:.2f}) is not a whole number.",
                    medicine_index=mi,
                    dispense_index=di,
                    ndc=ndc11,
                    rx_no=disp.get("rx_no"),
                    actual=f"{qty} / {days}",
                    suggestion="Verify quantity dispensed and days supply.",
                )
            )


async def _module_i(
    session: AsyncSession,
    medical_store_id: int,
    medicines: list[dict],
    alerts: list[Alert],
) -> None:
    """Module I — stock on hand, one alert per medicine.

    A dispense drawn against a drug the store has no stock record for (or a
    row sitting at zero) means the purchase side is missing: the invoice that
    brought it in was never uploaded, or came in under a different NDC. Saving
    anyway is legitimate — it just drives the row negative — so this blocks the
    save the same way every other ERROR does and clears with force-save.

    Ungated on purpose: unlike Modules A–H this runs on every plan.
    """
    codes = {
        code
        for med in medicines
        if (code := _normalize_inventory_code(med.get("ndc")))
    }
    if not codes:
        return

    rows = await session.execute(
        select(MedicineInventory.code, MedicineInventory.quantity).where(
            MedicineInventory.medical_store_id == medical_store_id,
            MedicineInventory.code.in_(codes),
            # Explicit rather than relying on the global soft-delete loader
            # criteria, which is documented for entity loads — this is a
            # column-only select, and a deleted stock row must read as "no
            # inventory" here, matching what every list endpoint shows.
            MedicineInventory.IsDeleted.is_(False),
        )
    )
    on_hand: dict[str, Decimal] = {code: qty for code, qty in rows.all()}

    for mi, med in enumerate(medicines):
        code = _normalize_inventory_code(med.get("ndc"))
        if not code:
            continue  # FIELD already flagged MALFORMED_NDC
        quantity = on_hand.get(code)
        if quantity is None:
            alerts.append(
                Alert(
                    module="I",
                    code="NO_INVENTORY_FOR_DISPENSE",
                    severity="ERROR",
                    message=(
                        "No inventory on hand for this NDC — can't find inventory "
                        "for this dispense."
                    ),
                    medicine_index=mi,
                    ndc=code,
                    field="ndc",
                    actual=med.get("drug_name") or "",
                    expected="a stocked NDC",
                    suggestion=(
                        "Upload the invoice that brought this drug in, or check "
                        "the NDC — nothing was ever received under this code."
                    ),
                )
            )
        elif quantity <= 0:
            alerts.append(
                Alert(
                    module="I",
                    code="NO_INVENTORY_FOR_DISPENSE",
                    severity="ERROR",
                    message=(
                        f"Inventory for this NDC is {quantity} — can't find "
                        "inventory for this dispense."
                    ),
                    medicine_index=mi,
                    ndc=code,
                    field="ndc",
                    actual=str(quantity),
                    expected="> 0",
                    suggestion=(
                        "Upload the purchase invoice for this drug before "
                        "dispensing it, or correct the stock count."
                    ),
                )
            )


def _normalize_inventory_code(ndc: Any) -> str | None:
    """The inventory key for a dispense's NDC.

    Delegates to the very function the inventory writer uses
    (`subtract_dispense_quantities` → `_normalize_ndc`), so Module I looks up
    exactly the code the stock is keyed under. A local rule here would drift:
    an 11-digit check on the raw string skips hyphenated NDCs like
    "12345-6789-01", which the writer happily normalizes and tracks — the
    check would silently pass on rows that really do have a stock row.
    """
    from services.inventory_service import _normalize_ndc

    code = (str(ndc) if ndc is not None else "").strip()
    return _normalize_ndc(code) if code else None


async def validate_tier2(
    session: AsyncSession,
    report_data: dict,
    tier1_report: ValidationReport | None = None,
    granted: set[str] | None = None,
    medical_store_id: int | None = None,
) -> ValidationReport:
    """
    Tier-1 + FDA-dependent checks merged into one ValidationReport.

    Caller should pass `tier1_report` from a prior `validate_tier1` run so
    we don't recompute the pure-data checks. If None, Tier-1 is rerun.

    `granted` = the store's ``Plan.features`` flag set (``None`` → run all).
    Modules A/B/C are gated per plan; when none are granted the FDA lookup is
    skipped entirely (saving ~1–2 s/NDC). Skipped modules emit ``PLAN_LOCKED``.

    `medical_store_id` enables Module I (stock on hand), which is ungated —
    every plan gets it. Omit it (e.g. the worker's plan-less preview) and the
    check is simply skipped rather than guessed at.
    """
    if tier1_report is None:
        from services.validation.tier1 import validate_tier1

        tier1_report = validate_tier1(report_data, granted=granted)

    alerts: list[Alert] = list(tier1_report.alerts)
    medicines: list[dict] = report_data.get("medicines") or []
    today = datetime.utcnow().date()

    need_a = has(granted, "discontinued_drug_detection")   # Module A (Ultimate)
    need_b = has(granted, "ndc_claim_mismatch_checks")     # Module B (Ultimate)
    need_c = has(granted, "pack_size_billed_reconciliation")  # Module C (Advanced)

    # Only pay for FDA lookups if at least one FDA-dependent module is granted.
    if need_a or need_b or need_c:
        for mi, med in enumerate(medicines):
            ndc = (med.get("ndc") or "").strip()
            if not re.fullmatch(r"\d{11}", ndc):
                continue  # FIELD already flagged MALFORMED_NDC
            try:
                cache_row = await get_or_fetch(session, ndc)
            except Exception as exc:
                logger.warning("NDC lookup failed: ndc11={n} err={e}", n=ndc, e=exc)
                if need_a:
                    alerts.append(
                        Alert(
                            module="A",
                            code="NDC_LOOKUP_FAILED",
                            severity="INDETERMINATE",
                            message=f"FDA / cache lookup failed: {exc}",
                            medicine_index=mi,
                            ndc=ndc,
                        )
                    )
                continue
            drug_name = med.get("drug_name") or ""
            if need_a:
                _module_a(mi, ndc, med, cache_row, today, alerts, strict_date_check=True)
            if need_b:
                _module_b(mi, ndc, drug_name, cache_row, alerts)
            if need_c:
                _module_c(mi, ndc, med, cache_row, alerts)
            _module_d(mi, ndc, med, alerts)

    # Module I — stock on hand. Outside the A/B/C block on purpose: it needs no
    # FDA lookup and no plan flag, so it runs even when every gated module is
    # locked.
    if medical_store_id is not None:
        await _module_i(session, medical_store_id, medicines, alerts)

    # One lock marker per module the plan doesn't include.
    if not need_a:
        alerts.append(plan_locked_alert("A", "discontinued_drug_detection"))
    if not need_b:
        alerts.append(plan_locked_alert("B", "ndc_claim_mismatch_checks"))
    if not need_c:
        alerts.append(plan_locked_alert("C", "pack_size_billed_reconciliation"))

    return ValidationReport(
        summary=summarize(alerts, tier1=True, tier2=True),
        alerts=alerts,
        grand_total=tier1_report.grand_total,
        per_patient=tier1_report.per_patient,
    )
