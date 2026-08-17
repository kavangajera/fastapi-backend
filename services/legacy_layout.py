"""Detection and validation for the deterministic legacy dispense layout."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from loguru import logger

_NDC = re.compile(r"^\d{11}$")
_HEADER_NOISE = re.compile(r"Qty Disp|Date Filled|Pat Name|Pres Addr|Inventory Bucket", re.I)


def validated_legacy_extract(extractor: Callable[[bytes], dict], file_bytes: bytes) -> dict | None:
    """Return a high-confidence legacy result, otherwise select the Gemini path."""
    try:
        report = extractor(file_bytes)
    except Exception as exc:
        logger.info("Legacy layout rejected during inspection: {error}", error=exc)
        return None

    medicines = report.get("medicines", [])
    dispenses = [row for medicine in medicines for row in medicine.get("dispenses", [])]

    def _reject(reason: str, **detail: Any) -> None:
        # Rejection sends the whole document down the paid LLM path, so say
        # WHY. Without this the fallback is silent and a regression in the
        # regex extractor is indistinguishable from a genuinely unfamiliar
        # layout once it is running in production.
        logger.info(
            "Legacy layout rejected ({reason}): medicines={medicines} dispenses={dispenses} {detail}",
            reason=reason,
            medicines=len(medicines),
            dispenses=len(dispenses),
            detail=detail or "",
        )

    if not medicines or not dispenses:
        _reject("no medicines or no dispense rows parsed")
        return None

    bad_medicine = next(
        (
            medicine
            for medicine in medicines
            if not _NDC.fullmatch(str(medicine.get("ndc") or ""))
            or not medicine.get("drug_name")
            or _HEADER_NOISE.search(str(medicine.get("drug_name")))
        ),
        None,
    )
    if bad_medicine is not None:
        _reject(
            "malformed medicine",
            ndc=bad_medicine.get("ndc"),
            drug_name=(bad_medicine.get("drug_name") or "")[:60],
        )
        return None

    bad_row = next(
        (row for row in dispenses if not row.get("rx_no") or not row.get("date_filled")), None
    )
    if bad_row is not None:
        _reject(
            "dispense row missing rx_no/date_filled",
            rx_no=bad_row.get("rx_no"),
            date_filled=bad_row.get("date_filled"),
        )
        return None

    # A given rx_no legitimately repeats across refills (same prescription,
    # different `ref` counter and fill date) — only reject when the same
    # (rx_no, ref) pair repeats, which means a row was actually parsed
    # twice by the extractor rather than a genuine refill.
    rx_ref_pairs = [(str(row["rx_no"]), str(row.get("ref"))) for row in dispenses]
    if len(rx_ref_pairs) != len(set(rx_ref_pairs)):
        seen: set = set()
        dupe = next((p for p in rx_ref_pairs if p in seen or seen.add(p)), None)
        _reject("duplicate (rx_no, ref) pair — row parsed twice", pair=dupe)
        return None

    # Deliberately no cross-check of parsed row counts against any printed
    # total (grand total or per-NDC "Total For:"). Those totals are the
    # source document's own arithmetic and can be internally inconsistent
    # (seen in practice) independent of whether every row was parsed
    # correctly. Acceptance is purely structural: every row has the fields
    # a detail row must have, and every medicine has a well-formed NDC and
    # name. That's what "this PDF matches the known layout" means here.

    logger.info(
        "Legacy layout accepted: medicines={medicines} dispenses={dispenses}",
        medicines=len(medicines),
        dispenses=len(dispenses),
    )
    return _merge_medicines_by_ndc(report)


def _merge_medicines_by_ndc(report: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, dict] = {}
    order: list[str] = []
    for medicine in report["medicines"]:
        ndc = medicine["ndc"]
        if ndc not in merged:
            merged[ndc] = medicine
            order.append(ndc)
            continue
        target = merged[ndc]
        target["dispenses"].extend(medicine.get("dispenses", []))
        if len(medicine["drug_name"]) < len(target["drug_name"]):
            target["drug_name"] = medicine["drug_name"]
        for key, value in (medicine.get("totals") or {}).items():
            if value is not None:
                target.setdefault("totals", {})[key] = value
    report["medicines"] = [merged[ndc] for ndc in order]
    return report
