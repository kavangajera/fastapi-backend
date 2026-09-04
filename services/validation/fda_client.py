"""
services/validation/fda_client.py
─────────────────────────────────
Thin async wrapper around `services.barcode_scanner.BarcodeScannerService.query_fda`.

Why a wrapper:
    - the underlying scanner is blocking (requests + retry loop); we run it
      via asyncio.to_thread so the event loop is never blocked,
    - we normalize the 11-digit NDC to the up-to-4 NDC10 hyphenated
      candidates FDA accepts,
    - we extract the per-NDC fields the validation engine needs into a
      dict that lines up 1:1 with `models.MedicineNdcCache`.

`is_unit_of_use` is a derived flag — Module C reads it without touching
strings. Keywords are intentionally narrow; if Module C starts missing
cases we extend this set.
"""

from __future__ import annotations

import asyncio
import json
import re
from decimal import Decimal, InvalidOperation

from loguru import logger

from services.barcode_scanner import BarcodeScannerService

_scanner = BarcodeScannerService()

_UOU_KEYWORDS = (
    "inhal",
    "aerosol",
    "metered",
    "pen ",
    "kit",
    "sensor",
    "strip",
    "lancet",
    "prefill",
    "auto-injector",
    "syringe",
)


def ndc11_to_ndc10_candidates(ndc11: str) -> list[str]:
    """Return every plausible hyphenated NDC10 form for an 11-digit NDC.

    The FDA Drug NDC Directory stores `packaging.package_ndc` in 4-4-2,
    5-3-2, or 5-4-1 form; we try each shape produced by stripping a
    leading zero in the matching segment.
    """
    if not re.fullmatch(r"\d{11}", ndc11 or ""):
        return []
    cands: list[str] = []
    if ndc11[0] == "0":
        cands.append(f"{ndc11[1:5]}-{ndc11[5:9]}-{ndc11[9:11]}")  # 4-4-2
    if ndc11[5] == "0":
        cands.append(f"{ndc11[:5]}-{ndc11[6:9]}-{ndc11[9:11]}")  # 5-3-2
    if ndc11[10] == "0":
        cands.append(f"{ndc11[:5]}-{ndc11[5:9]}-{ndc11[10]}")  # 5-4-1
    cands.append(f"{ndc11[:5]}-{ndc11[5:9]}-{ndc11[9:11]}")  # raw 5-4-2 fallback
    return cands


def _is_unit_of_use(dosage_form: str | None, package_description: str | None) -> bool:
    hay = f"{dosage_form or ''} {package_description or ''}".lower()
    return any(k in hay for k in _UOU_KEYWORDS)


_PACK_SEG_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s+([A-Za-z][A-Za-z,\-\s]*?)\s+in\s+\d+(?:\.\d+)?\s+[A-Za-z].*$",
    re.IGNORECASE,
)


def parse_pack_size(package_description: str | None) -> tuple[Decimal, str] | None:
    """Best-effort numeric pack-size extraction from an FDA `package_description`.

    FDA package descriptions look like "<N> <UNIT> in <N> <CONTAINER>" for a
    simple package (e.g. "120 SPRAY, METERED in 1 BOTTLE" -> (120, "SPRAY,
    METERED")), or a compound "<outer> / <inner>" shape for injectables
    (e.g. "1 VIAL, SINGLE-DOSE in 1 CARTON / 8.5 mL in 1 VIAL, SINGLE-DOSE").
    For a compound description the LAST "/"-delimited segment is the
    fill-quantity-per-immediate-container line, which is the number that
    actually matters for whole-multiple reconciliation (e.g. 8.5 mL/vial —
    a legitimate non-integer "pack size"). For a simple description the
    only segment is used directly.

    Returns (qty, unit_noun) or None whenever the shape doesn't confidently
    match — this never guesses at a number.
    """
    if not package_description:
        return None
    segments = [s.strip() for s in package_description.split("/") if s.strip()]
    if not segments:
        return None
    target = segments[-1]
    m = _PACK_SEG_RE.match(target)
    if not m:
        return None
    try:
        qty = Decimal(m.group(1))
    except InvalidOperation:
        return None
    if qty <= 0:
        return None
    return qty, m.group(2).strip().rstrip(",")


def _normalize_fda(payload: dict | None, ndc11: str, matched: str | None) -> dict:
    """Project an FDA result dict into our cache row shape."""
    if not payload:
        return {
            "ndc11": ndc11,
            "matched_package_ndc": None,
            "brand_name": None,
            "generic_name": None,
            "dosage_form": None,
            "route": None,
            "marketing_category": None,
            "marketing_start_date": None,
            "marketing_end_date": None,
            "listing_expiration_date": None,
            "package_description": None,
            "is_unit_of_use": False,
            "found_in_fda": False,
            "raw_payload": None,
            "labeler_name": None,
            "strength_text": None,
            "pack_size_qty": None,
            "pack_size_uom": None,
        }
    packaging = (payload.get("packaging") or [{}])[0]
    pkg_desc = packaging.get("description")
    df = payload.get("dosage_form")
    pack_size = parse_pack_size(pkg_desc)
    active_ingredients = payload.get("active_ingredients") or []
    strength_text = (
        ", ".join(
            f"{ai.get('name', '')} {ai.get('strength', '')}".strip()
            for ai in active_ingredients
            if ai.get("name") or ai.get("strength")
        )
        or None
    )
    return {
        "ndc11": ndc11,
        "matched_package_ndc": matched,
        "brand_name": (payload.get("brand_name") or None),
        "generic_name": (payload.get("generic_name") or None),
        "dosage_form": df,
        "route": (
            ",".join(payload.get("route", []))
            if isinstance(payload.get("route"), list)
            else payload.get("route")
        ),
        "marketing_category": payload.get("marketing_category"),
        "marketing_start_date": packaging.get("marketing_start_date") or payload.get("marketing_start_date"),
        "marketing_end_date": packaging.get("marketing_end_date") or payload.get("marketing_end_date"),
        "listing_expiration_date": payload.get("listing_expiration_date"),
        "package_description": pkg_desc,
        "is_unit_of_use": _is_unit_of_use(df, pkg_desc),
        "found_in_fda": True,
        "raw_payload": json.dumps(payload, ensure_ascii=False),
        "labeler_name": payload.get("labeler_name") or None,
        "strength_text": strength_text,
        "pack_size_qty": pack_size[0] if pack_size else None,
        "pack_size_uom": pack_size[1] if pack_size else None,
    }


def _fetch_sync(ndc11: str) -> dict:
    """Blocking FDA call; wrap with asyncio.to_thread from async code."""
    for cand in ndc11_to_ndc10_candidates(ndc11):
        try:
            resp, _, used = _scanner.query_fda(cand)
        except Exception as exc:  # pragma: no cover — network is unpredictable
            logger.warning("FDA call failed for {c}: {e}", c=cand, e=exc)
            continue
        if isinstance(resp, dict) and resp.get("results"):
            return _normalize_fda(resp["results"][0], ndc11, used or cand)
    return _normalize_fda(None, ndc11, None)


async def fetch_fda(ndc11: str) -> dict:
    """Async entry point used by ndc_cache.get_or_fetch."""
    return await asyncio.to_thread(_fetch_sync, ndc11)
