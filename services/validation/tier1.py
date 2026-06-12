"""
services/validation/tier1.py
────────────────────────────
Pure-data checks — no external HTTP, no DB beyond what's already in the
extracted report dict. Safe to run from inside the Kafka handler so users
see alerts the moment extraction finishes.

Modules covered:
    FIELD-SANITY  drug_name bleed, duplicate NDC within report,
                  malformed NDC, missing rx_no
    D (Tier 3)    days_supply ≤ 0 → ERROR; qty/days out of bounds → WARNING
    E             same patient_key + same NDC ≥ 2 → WARNING
    F             same patient_key + same NDC + same canonical insurance ≥ 2 → ERROR
    G             grand-total recompute + per-patient totals + unpaid lines
    H             refills_remaining ('ref' == '0') → INFO listing

Modules A/B/C need FDA — they live in tier2.
"""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from core.config import settings
from schemas.validation import (
    Alert,
    GrandTotalRecompute,
    PerPatientTotal,
    ValidationReport,
)
from services.validation.insurance_key import canonical_insurance
from services.validation.patient_key import (
    derive_patient_key,
    patient_label,
)
from services.validation.severity import summarize

_DRUG_BLEED_MARKERS = (
    "Pres Addr",
    "Pat Addr",
    "Pat Ph#",
    "Ins Paid",
    "Ins Code",
    "Qty Ord",
    "Inventory Bucket",
)
_NDC_RE = re.compile(r"^\d{11}$")


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        # The extractor sometimes emits floats stringified ("30.0", "1.0");
        # float() then int() handles both shapes.
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return None


def _safe_str(d: Decimal | None) -> str | None:
    return None if d is None else str(d)


# ─────────────────────────────────────────────────────────────────────
# FIELD-SANITY
# ─────────────────────────────────────────────────────────────────────


def _check_field_sanity(medicines: list[dict], alerts: list[Alert]) -> None:
    seen_ndcs: dict[str, list[int]] = defaultdict(list)

    for mi, med in enumerate(medicines):
        ndc = med.get("ndc") or ""
        name = med.get("drug_name") or ""

        if not _NDC_RE.fullmatch(ndc):
            alerts.append(
                Alert(
                    module="FIELD",
                    code="MALFORMED_NDC",
                    severity="ERROR",
                    message=f"NDC '{ndc}' is not an 11-digit number.",
                    medicine_index=mi,
                    ndc=ndc,
                    field="ndc",
                    suggestion="Re-enter as 11 digits with leading zeros (no hyphens).",
                )
            )

        if any(marker in name for marker in _DRUG_BLEED_MARKERS) or len(name) > 80:
            alerts.append(
                Alert(
                    module="FIELD",
                    code="DRUG_NAME_BLEED",
                    severity="ERROR",
                    message="drug_name contains column-label text from adjacent fields.",
                    medicine_index=mi,
                    ndc=ndc,
                    field="drug_name",
                    actual=name[:100],
                    suggestion=(
                        "Truncate the name after the dosage form (TAB/CAP/INH/INJ/...). "
                        "Verify the parser settings for this report layout."
                    ),
                )
            )

        if not med.get("dispenses"):
            alerts.append(
                Alert(
                    module="FIELD",
                    code="MEDICINE_NO_DISPENSES",
                    severity="WARNING",
                    message="Medicine has no dispense rows attached.",
                    medicine_index=mi,
                    ndc=ndc,
                )
            )

        seen_ndcs[ndc].append(mi)

    for ndc, indices in seen_ndcs.items():
        if len(indices) >= 2 and _NDC_RE.fullmatch(ndc):
            alerts.append(
                Alert(
                    module="FIELD",
                    code="DUPLICATE_NDC_IN_REPORT",
                    severity="ERROR",
                    message=(
                        f"NDC {ndc} appears in {len(indices)} medicine rows in "
                        "this report; merge them into one before saving."
                    ),
                    ndc=ndc,
                    expected=1,
                    actual=len(indices),
                    suggestion="Combine the duplicate medicine rows into one with all dispenses.",
                )
            )


# ─────────────────────────────────────────────────────────────────────
# Module D — qty / days_supply
# ─────────────────────────────────────────────────────────────────────


def _check_days_supply(medicines: list[dict], alerts: list[Alert]) -> None:
    rmax = settings.DAYS_SUPPLY_RATE_MAX
    rmin = settings.DAYS_SUPPLY_RATE_MIN

    for mi, med in enumerate(medicines):
        ndc = med.get("ndc")
        for di, disp in enumerate(med.get("dispenses", [])):
            days = _to_int(disp.get("days_supply"))
            qty = _to_decimal(disp.get("qty_disp"))

            if days is None or days <= 0:
                alerts.append(
                    Alert(
                        module="D",
                        code="DAYS_SUPPLY_INVALID",
                        severity="ERROR",
                        message="days_supply must be > 0.",
                        medicine_index=mi,
                        dispense_index=di,
                        ndc=ndc,
                        rx_no=disp.get("rx_no"),
                        field="days_supply",
                        actual=days,
                        suggestion="Set days_supply to a positive integer.",
                    )
                )
                continue
            if qty is None or qty <= 0:
                continue
            rate = float(qty) / days
            if rate > rmax or rate < rmin:
                alerts.append(
                    Alert(
                        module="D",
                        code="DAYS_SUPPLY_RATE_OUT_OF_BOUNDS",
                        severity="WARNING",
                        message=(
                            f"qty/days_supply = {rate:.3f} is outside the generic "
                            f"plausible range [{rmin}, {rmax}]."
                        ),
                        medicine_index=mi,
                        dispense_index=di,
                        ndc=ndc,
                        rx_no=disp.get("rx_no"),
                        field="days_supply",
                        actual=f"qty={qty} days={days} rate={rate:.3f}",
                        suggestion="Confirm qty_disp and days_supply against the prescription.",
                    )
                )


# ─────────────────────────────────────────────────────────────────────
# Modules E + F — repeat dispensing
# ─────────────────────────────────────────────────────────────────────


def _check_repeat(medicines: list[dict], alerts: list[Alert]) -> None:
    by_patient_ndc: dict[tuple[str, str], list[tuple[int, int, dict]]] = defaultdict(list)
    by_patient_ndc_ins: dict[tuple[str, str, str | None], list[tuple[int, int, dict]]] = (
        defaultdict(list)
    )

    for mi, med in enumerate(medicines):
        ndc = med.get("ndc") or ""
        for di, disp in enumerate(med.get("dispenses", [])):
            pk = derive_patient_key(
                disp.get("pat_name"), disp.get("pat_phone"), disp.get("pat_addr")
            )
            ins = canonical_insurance(disp.get("ins_code"))
            by_patient_ndc[(pk, ndc)].append((mi, di, disp))
            by_patient_ndc_ins[(pk, ndc, ins)].append((mi, di, disp))

    for (pk, ndc), entries in by_patient_ndc.items():
        if len(entries) >= 2:
            alerts.append(
                Alert(
                    module="E",
                    code="REPEAT_PATIENT_DRUG",
                    severity="WARNING",
                    message=(f"Same patient appears {len(entries)} times for NDC {ndc}."),
                    medicine_index=entries[0][0],
                    dispense_index=entries[0][1],
                    ndc=ndc,
                    patient_key=pk,
                    actual=[e[2].get("rx_no") for e in entries],
                    suggestion=("Confirm these are legitimate refills, not duplicates."),
                )
            )

    for (pk, ndc, ins), entries in by_patient_ndc_ins.items():
        if len(entries) >= 2:
            alerts.append(
                Alert(
                    module="F",
                    code="REPEAT_PATIENT_DRUG_INSURANCE",
                    severity="ERROR",
                    message=(
                        f"Same patient + NDC {ndc} + insurance {ins} appears "
                        f"{len(entries)} times — strongest duplicate-billing signal."
                    ),
                    medicine_index=entries[0][0],
                    dispense_index=entries[0][1],
                    ndc=ndc,
                    patient_key=pk,
                    actual=[e[2].get("rx_no") for e in entries],
                    suggestion=("Investigate. Reverse one of the claims if duplicate."),
                )
            )


# ─────────────────────────────────────────────────────────────────────
# Module H — refills remaining == 0
# ─────────────────────────────────────────────────────────────────────


def _check_zero_refills(medicines: list[dict], alerts: list[Alert]) -> None:
    for mi, med in enumerate(medicines):
        for di, disp in enumerate(med.get("dispenses", [])):
            ref = disp.get("ref")
            if ref is None:
                continue
            try:
                # Extractor sometimes emits floats stringified ("0.0", "1.0"); float() handles both.
                if int(float(str(ref).strip())) == 0:
                    alerts.append(
                        Alert(
                            module="H",
                            code="ZERO_REFILLS_REMAINING",
                            severity="INFO",
                            message="No refills remaining on this prescription.",
                            medicine_index=mi,
                            dispense_index=di,
                            ndc=med.get("ndc"),
                            rx_no=disp.get("rx_no"),
                            patient_key=derive_patient_key(
                                disp.get("pat_name"),
                                disp.get("pat_phone"),
                                disp.get("pat_addr"),
                            ),
                            suggestion=("Patient may need a new prescription before next fill."),
                        )
                    )
            except (ValueError, TypeError):
                continue


# ─────────────────────────────────────────────────────────────────────
# Module G — grand total + per-patient + unpaid
# ─────────────────────────────────────────────────────────────────────


def _grand_total_recompute(
    medicines: list[dict], grand_total_printed: dict, alerts: list[Alert]
) -> tuple[GrandTotalRecompute, list[PerPatientTotal]]:
    rx_count = 0
    sum_price = Decimal("0")
    sum_ins_paid = Decimal("0")
    sum_qty = Decimal("0")

    per_patient_acc: dict[str, dict] = defaultdict(
        lambda: {
            "rx_count": 0,
            "price": Decimal("0"),
            "ins_paid": Decimal("0"),
            "label": "?",
        }
    )

    for med in medicines:
        for disp in med.get("dispenses", []):
            rx_count += 1
            price = _to_decimal(disp.get("price")) or Decimal("0")
            ins = _to_decimal(disp.get("ins_paid")) or Decimal("0")
            qty = _to_decimal(disp.get("qty_disp")) or Decimal("0")
            sum_price += price
            sum_ins_paid += ins
            sum_qty += qty

            pk = derive_patient_key(
                disp.get("pat_name"), disp.get("pat_phone"), disp.get("pat_addr")
            )
            slot = per_patient_acc[pk]
            slot["rx_count"] += 1
            slot["price"] += price
            slot["ins_paid"] += ins
            slot["label"] = patient_label(disp.get("pat_name"))

    printed_rx = _to_int(grand_total_printed.get("total_rx_count"))
    printed_price = _to_decimal(grand_total_printed.get("total_price"))
    printed_cost = _to_decimal(grand_total_printed.get("total_cost"))

    delta_rx = (printed_rx - rx_count) if printed_rx is not None else None
    delta_price = _safe_str(printed_price - sum_price) if printed_price is not None else None

    gt = GrandTotalRecompute(
        printed_rx_count=printed_rx,
        printed_total_price=_safe_str(printed_price),
        printed_total_cost=_safe_str(printed_cost),
        recomputed_rx_count=rx_count,
        recomputed_sum_price=str(sum_price),
        recomputed_sum_ins_paid=str(sum_ins_paid),
        recomputed_sum_qty=str(sum_qty),
        delta_rx_count=delta_rx,
        delta_total_price=delta_price,
    )

    if delta_rx is not None and delta_rx != 0:
        alerts.append(
            Alert(
                module="G",
                code="GRAND_TOTAL_DELTA_RX",
                severity="INFO",
                message=(
                    f"Printed rx_count={printed_rx} vs recomputed={rx_count}; "
                    "use the recomputed value (spec §4.4)."
                ),
                expected=str(rx_count),
                actual=str(printed_rx),
            )
        )
    if printed_price is not None and printed_price != sum_price:
        alerts.append(
            Alert(
                module="G",
                code="GRAND_TOTAL_DELTA_PRICE",
                severity="INFO",
                message=(f"Printed total_price={printed_price} vs recomputed={sum_price}."),
                expected=str(sum_price),
                actual=str(printed_price),
            )
        )

    # Unpaid lines (price > 0, ins_paid == 0).
    for mi, med in enumerate(medicines):
        for di, disp in enumerate(med.get("dispenses", [])):
            price = _to_decimal(disp.get("price")) or Decimal("0")
            ins = _to_decimal(disp.get("ins_paid")) or Decimal("0")
            if price > 0 and ins == 0:
                alerts.append(
                    Alert(
                        module="G",
                        code="UNPAID_LINE",
                        severity="WARNING",
                        message=(
                            f"price={price} but ins_paid=0 (ins_code={disp.get('ins_code')})."
                        ),
                        medicine_index=mi,
                        dispense_index=di,
                        ndc=med.get("ndc"),
                        rx_no=disp.get("rx_no"),
                        suggestion="Confirm cash sale vs insurance rejection.",
                    )
                )

    per_patient = [
        PerPatientTotal(
            patient_key=pk,
            patient_label=v["label"],
            rx_count=v["rx_count"],
            total_price=str(v["price"]),
            total_ins_paid=str(v["ins_paid"]),
            patient_responsibility=str(v["price"] - v["ins_paid"]),
        )
        for pk, v in sorted(per_patient_acc.items(), key=lambda kv: kv[1]["price"], reverse=True)
    ]

    return gt, per_patient


# ─────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────


def validate_tier1(report_data: dict) -> ValidationReport:
    """Run every pure-data check; return a fully-populated ValidationReport."""
    alerts: list[Alert] = []
    medicines: list[dict] = report_data.get("medicines") or []
    grand_total_printed: dict = report_data.get("grand_total") or {}

    _check_field_sanity(medicines, alerts)
    _check_days_supply(medicines, alerts)
    _check_repeat(medicines, alerts)
    _check_zero_refills(medicines, alerts)
    gt, per_patient = _grand_total_recompute(medicines, grand_total_printed, alerts)

    summary = summarize(alerts, tier1=True, tier2=False)
    return ValidationReport(summary=summary, alerts=alerts, grand_total=gt, per_patient=per_patient)
