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
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from schemas.validation import Alert, ValidationReport
from services.validation.ndc_cache import get_or_fetch
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


def _module_a(
    mi: int, ndc11: str, drug_name: str, cache_row, today: date, alerts: list[Alert]
) -> None:
    if cache_row is None or not cache_row.found_in_fda:
        alerts.append(
            Alert(
                module="A",
                code="NDC_NOT_FOUND",
                severity="WARNING",
                message=(
                    "NDC not present in FDA Drug NDC Directory — may be a medical "
                    "device, supply, or recently launched product."
                ),
                medicine_index=mi,
                ndc=ndc11,
                actual=drug_name,
                suggestion="Verify NDC manually; devices live in the FDA Device DB, not Drug.",
            )
        )
        return

    end_dt = _parse_yyyymmdd(cache_row.marketing_end_date)
    if end_dt and end_dt < today:
        alerts.append(
            Alert(
                module="A",
                code="NDC_DISCONTINUED",
                severity="ERROR",
                message=(
                    f"Marketing end date {end_dt.isoformat()} is in the past — "
                    "this NDC is discontinued."
                ),
                medicine_index=mi,
                ndc=ndc11,
                actual=cache_row.marketing_end_date,
                suggestion="Use a current NDC for this product before dispensing further.",
            )
        )
        return
    if end_dt:
        delta = (end_dt - today).days
        if delta < settings.NDC_LISTING_EXPIRY_INFO_DAYS:
            alerts.append(
                Alert(
                    module="A",
                    code="NDC_LISTING_EXPIRES_SOON",
                    severity="INFO",
                    message=(
                        f"Listing expires {end_dt.isoformat()} ({delta} days). "
                        "FDA listings are typically renewed annually."
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


async def validate_tier2(
    session: AsyncSession,
    report_data: dict,
    tier1_report: ValidationReport | None = None,
) -> ValidationReport:
    """
    Tier-1 + FDA-dependent checks merged into one ValidationReport.

    Caller should pass `tier1_report` from a prior `validate_tier1` run so
    we don't recompute the pure-data checks. If None, Tier-1 is rerun.
    """
    if tier1_report is None:
        from services.validation.tier1 import validate_tier1

        tier1_report = validate_tier1(report_data)

    alerts: list[Alert] = list(tier1_report.alerts)
    medicines: list[dict] = report_data.get("medicines") or []
    today = datetime.utcnow().date()

    for mi, med in enumerate(medicines):
        ndc = (med.get("ndc") or "").strip()
        if not re.fullmatch(r"\d{11}", ndc):
            continue  # FIELD already flagged MALFORMED_NDC
        try:
            cache_row = await get_or_fetch(session, ndc)
        except Exception as exc:
            logger.warning("NDC lookup failed: ndc11={n} err={e}", n=ndc, e=exc)
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
        _module_a(mi, ndc, drug_name, cache_row, today, alerts)
        _module_b(mi, ndc, drug_name, cache_row, alerts)
        _module_c(mi, ndc, med, cache_row, alerts)

    return ValidationReport(
        summary=summarize(alerts, tier1=True, tier2=True),
        alerts=alerts,
        grand_total=tier1_report.grand_total,
        per_patient=tier1_report.per_patient,
    )
