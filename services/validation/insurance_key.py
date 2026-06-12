"""
services/validation/insurance_key.py
────────────────────────────────────
Per spec §6.5: insurance codes are printed with wrapping / variant forms
(e.g. EMPIRE → EMPIREBCBS, MMS208 vs MMS2084 column-bleed, ADV / AD2 etc).
The canonicalizer folds known variants to a single key so Module F can
detect true duplicates.

The raw code is always preserved alongside the canonical key in the alert
payload for human review.
"""

from __future__ import annotations

import re

# Known synonym groups → canonical code.
_SYNONYMS: dict[str, str] = {
    # Empire BCBS family
    "EMPIRE": "EMPIRE_BCBS",
    "EMPIREBCBS": "EMPIRE_BCBS",
    "EMPIRE BCBS": "EMPIRE_BCBS",
    # Anthem variants
    "ANTHE": "ANTHEM",
    "ANTHEM": "ANTHEM",
    "ANTHEM BCBS": "ANTHEM",
    # Aetna
    "AETMCR": "AETNA_MCR",
    "AETNA": "AETNA",
    # Express Scripts
    "ES3": "EXPRESS_SCRIPTS",
    "ESI": "EXPRESS_SCRIPTS",
    # Medicaid New York coding family
    "MCD": "MEDICAID",
    "MMS205": "MEDICAID_MMS205",
    "MMS208": "MEDICAID_MMS208",
    "MMS2084": "MEDICAID_MMS208",
    "MMS2085": "MEDICAID_MMS205",
    # Advantage placeholders
    "ADV": "ADVANTAGE",
    "AD1": "ADVANTAGE_1",
    "AD2": "ADVANTAGE_2",
}

_WS = re.compile(r"\s+")


def canonical_insurance(code: str | None) -> str | None:
    if not code:
        return None
    cleaned = _WS.sub(" ", code).strip().upper()
    if not cleaned:
        return None
    if cleaned in _SYNONYMS:
        return _SYNONYMS[cleaned]
    # Strip trailing single digits that are likely column-bleed (e.g. "MMS2084 7")
    head = cleaned.split(" ", 1)[0]
    if head in _SYNONYMS:
        return _SYNONYMS[head]
    return cleaned  # unknown — pass through as canonical
