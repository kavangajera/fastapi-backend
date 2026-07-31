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
    if not medicines or not dispenses:
        return None
    if any(
        not _NDC.fullmatch(str(medicine.get("ndc") or ""))
        or not medicine.get("drug_name")
        or _HEADER_NOISE.search(str(medicine.get("drug_name")))
        for medicine in medicines
    ):
        return None
    if any(not row.get("rx_no") or not row.get("date_filled") for row in dispenses):
        return None
    rx_numbers = [str(row["rx_no"]) for row in dispenses]
    if len(rx_numbers) != len(set(rx_numbers)):
        return None
    reported_count = str(report.get("grand_total", {}).get("total_rx_count") or "")
    if reported_count and reported_count.isdigit() and int(reported_count) != len(dispenses):
        return None

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
