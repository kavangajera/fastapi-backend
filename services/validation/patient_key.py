"""
services/validation/patient_key.py
──────────────────────────────────
Stable, de-identified patient key per spec §6.3:
    patient_key = sha1(upper(strip(name)) + "|" + digits(phone) + "|" + zip5)

The key is used to group dispenses across rows without persisting raw PHI
in the alert payload or logs. Spec §13: NDC-only in external lookups, no
PHI in logs.
"""

from __future__ import annotations

import hashlib
import re

_DIGITS = re.compile(r"\d+")
_ZIP5 = re.compile(r"\b(\d{5})(?:[-\s]?\d{4})?\b")


def digits_only(s: str | None) -> str:
    if not s:
        return ""
    return "".join(_DIGITS.findall(s))


def extract_zip5(addr: str | None) -> str:
    if not addr:
        return ""
    m = _ZIP5.search(addr)
    return m.group(1) if m else ""


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    return " ".join(name.upper().strip().split())


def derive_patient_key(name: str | None, phone: str | None, address: str | None) -> str:
    parts = (
        normalize_name(name),
        digits_only(phone),
        extract_zip5(address),
    )
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def patient_label(name: str | None) -> str:
    """Light de-id label for UI: 'CEDENO, B.' from 'CEDENO, BRANDON'."""
    if not name:
        return "?"
    parts = [p.strip() for p in name.split(",")]
    if len(parts) >= 2 and parts[1]:
        return f"{parts[0]}, {parts[1][0]}."
    return parts[0]
