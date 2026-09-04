"""
services/validation/date_utils.py
──────────────────────────────────
Shared date parsing for FDA data (`YYYYMMDD` strings, as returned in
`MedicineNdcCache.marketing_start_date`/`marketing_end_date`).
"""

from __future__ import annotations

from datetime import date


def parse_yyyymmdd(s: str | None) -> date | None:
    if not s or len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None
