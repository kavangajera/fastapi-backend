"""
services/barcode_pairing.py
───────────────────────────
Scan up to 2 images and pair the barcode (1D, carries NDC) with the
datamatrix (2D, carries GTIN/serial/expiry/lot). Returns a single
flat dict shaped to slot directly into an invoice line item's
`{fda_*, dm_*, verified, ndc11}` fields.

Cases this handles:
    - Both barcode + datamatrix on a single image.
    - One image has only the barcode, the other has only the datamatrix.
    - Two images that both have only barcodes (or both only datamatrices)
      → reported under `unmatched` so the caller knows.

NO DB writes — pure extraction + pairing. Used by the barcode Kafka
handler.
"""

from __future__ import annotations

import base64
from datetime import date, datetime
from zoneinfo import ZoneInfo

from loguru import logger

from core.config import settings
from services.barcode_scanner import BarcodeScannerService
from services.datamatrix_scanner import scan_image_bytes
from services.ndc_utils import digits_only, ndc10_to_ndc11_from_package_ndc

_scanner = BarcodeScannerService()


def _extract_package_ndc(fda_data: dict | None) -> str | None:
    if not isinstance(fda_data, dict):
        return None
    for result in fda_data.get("results") or []:
        for pack in result.get("packaging") or []:
            package_ndc = pack.get("package_ndc")
            if package_ndc:
                return package_ndc
    return None


def _pick_datamatrix_payload(dm_payload: dict | None) -> dict | None:
    if not dm_payload or dm_payload.get("error"):
        return None
    items = dm_payload.get("detected_items")
    if isinstance(items, list) and items:
        return items[0]
    return dm_payload


def _parse_dm_expiry(expiry_value: str | None) -> date | None:
    if not expiry_value:
        return None
    try:
        return date.fromisoformat(expiry_value)
    except ValueError:
        return None


def _build_merged(
    barcode_info: dict,
    dm_info: dict,
    fda_data: dict | None,
) -> dict:
    fda_package_ndc = _extract_package_ndc(fda_data)
    fda_ndc11 = ndc10_to_ndc11_from_package_ndc(fda_package_ndc) if fda_package_ndc else None
    raw_ndc = barcode_info.get("ndc")
    ndc_digits = digits_only(raw_ndc or "")
    ndc11 = fda_ndc11 or (ndc_digits if len(ndc_digits) == 11 else None)

    expiry_date = _parse_dm_expiry(dm_info.get("expiration_date"))
    today = datetime.now(ZoneInfo(settings.APP_TIMEZONE)).date()
    fda_ok = bool(fda_package_ndc)
    expiry_ok = bool(expiry_date and expiry_date > today)
    verified = fda_ok and expiry_ok

    return {
        "ndc11": ndc11,
        "fda_package_ndc": fda_package_ndc,
        "fda_ndc11": fda_ndc11,
        "dm_gtin": dm_info.get("gtin"),
        "dm_serial_number": dm_info.get("serial_number"),
        "dm_expiration_date": dm_info.get("expiration_date"),
        "dm_lot_number": dm_info.get("lot_number"),
        "verified": verified,
    }


def pair_images(
    images: list[tuple[bytes, str]],
) -> dict:
    """
    Scan up to 2 images and emit the merged barcode+datamatrix result.

    Args:
        images: list of (file_bytes, filename) tuples — 1 or 2 entries.

    Returns:
        {
            "matched": [<merged dict>, ...],
            "unmatched": [{filename, reason, ...}, ...],
        }
        For a properly paired pair, len(matched) == 1. The list shape is
        kept so the caller can lift the first entry into a line item
        without special-casing the dict-vs-list shape.
    """
    if not images:
        return {"matched": [], "unmatched": [{"reason": "No images supplied."}]}

    pending_barcode: list[dict] = []
    pending_datamatrix: list[dict] = []
    matched: list[dict] = []
    unmatched: list[dict] = []

    for image_bytes, filename in images:
        if not image_bytes:
            unmatched.append({"filename": filename, "reason": "Image was empty."})
            continue

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        barcode_result = _scanner.process_barcode_base64(image_b64)
        dm_result = scan_image_bytes(
            image_bytes,
            debug=settings.DATAMATRIX_DEBUG,
            debug_dir=settings.DATAMATRIX_DEBUG_DIR,
            filename=filename,
        )

        barcode_data = barcode_result.get("extracted_data") or {}
        dm_payload = _pick_datamatrix_payload(dm_result)
        has_barcode = bool(barcode_data.get("ndc"))
        has_dm = bool(dm_payload)

        if has_barcode and has_dm:
            matched.append(_build_merged(barcode_data, dm_payload, barcode_result.get("fda_data")))
        elif has_barcode:
            if pending_datamatrix:
                dm_bundle = pending_datamatrix.pop(0)
                matched.append(
                    _build_merged(
                        barcode_data,
                        dm_bundle["payload"],
                        barcode_result.get("fda_data"),
                    )
                )
            else:
                pending_barcode.append(
                    {
                        "barcode": barcode_data,
                        "fda_data": barcode_result.get("fda_data"),
                        "filename": filename,
                    }
                )
        elif has_dm:
            if pending_barcode:
                bc = pending_barcode.pop(0)
                matched.append(_build_merged(bc["barcode"], dm_payload, bc["fda_data"]))
            else:
                pending_datamatrix.append({"payload": dm_payload, "filename": filename})
        else:
            unmatched.append({"filename": filename, "reason": "No barcode or datamatrix detected."})

    for leftover in pending_barcode:
        unmatched.append(
            {
                "filename": leftover.get("filename"),
                "reason": "Unpaired barcode (no datamatrix companion).",
            }
        )
    for leftover in pending_datamatrix:
        unmatched.append(
            {
                "filename": leftover.get("filename"),
                "reason": "Unpaired datamatrix.",
                "datamatrix": leftover.get("payload"),
            }
        )

    logger.info(
        "Barcode pairing: matched={m} unmatched={u}",
        m=len(matched),
        u=len(unmatched),
    )
    return {"matched": matched, "unmatched": unmatched}
