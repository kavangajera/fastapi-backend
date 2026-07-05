"""
core/record_ids.py
──────────────────
Pure constants + helpers for **server-generated** record identifiers.

A record identifier is the sync key the mobile app spec calls ``Source``:

    Source = <source_prefix> + <device_id> + <table_prefix> + <record_count>
             AN001            111111        STO             000002

Since the server is now the sole authority for these ids (clients no longer
send their own), the pieces are assembled here:

  - ``source_prefix``  — per-device platform code captured at login (e.g.
                         ``AN001``). Stored on the ``device`` row.
  - ``device_id``      — 6-char alphanumeric, one per device (see ``DEVICE_ID_*``).
  - ``table_prefix``   — 3-char code per table, from ``TABLE_PREFIXES``.
  - ``record_count``   — zero-padded, monotonic per (device, table); see
                         ``RECORD_COUNT_WIDTH``. Sourced from ``record_counter``.

This module is intentionally free of any DB / SQLAlchemy imports so it can be
used from schemas, services and migrations without cycles. The stateful part
(counter increment, device lookup) lives in ``services/record_id_service.py``.
"""

from __future__ import annotations

import re
import secrets
import string

# Default source prefix for callers that never went through a platform login
# (web / server-side writes) or whose device row is missing. Matches the
# mobile-app spec's example login source.
DEFAULT_SOURCE_PREFIX = "AN001"

# Device id: exactly 6 mixed-case alphanumeric characters.
DEVICE_ID_LENGTH = 6
DEVICE_ID_ALPHABET = string.ascii_letters + string.digits  # A-Za-z0-9
DEVICE_ID_PATTERN = re.compile(rf"^[A-Za-z0-9]{{{DEVICE_ID_LENGTH}}}$")

# Sentinel device used for records created outside a device session
# (web dashboard, background workers). Registered once so the generator's
# device lookup always resolves.
WEB_DEVICE_ID = "WEB000"

# Trailing counter width. 000001..999999 → 1,000,000 records per (device,
# table). Overflow simply widens the string (no crash) but breaks the fixed
# 20-char layout, so treat approaching this as a signal to widen the scheme.
RECORD_COUNT_WIDTH = 6

# 3-char code per table (keyed by ORM ``__tablename__``). Every AuditMixin
# table gets one; unknown tables fall back to ``fallback_table_prefix``.
TABLE_PREFIXES: dict[str, str] = {
    "user": "USR",
    "refresh_tokens": "RFT",
    "medical_store": "STO",
    "drug_reports": "DRP",
    "medicines": "MED",
    "dispenses": "DSP",
    "invoices": "INV",
    "invoice_line_items": "ILI",
    "invoice_summaries": "ISM",
    "medicine_inventory": "MIV",
    "medicine_ndc_cache": "NDC",
    "documents": "DOC",
    "activity_log": "ACT",
    "refill_dismissals": "RFD",
}


def fallback_table_prefix(table_name: str) -> str:
    """Deterministic 3-char prefix for a table without an explicit mapping."""
    letters = [c for c in table_name.upper() if c.isalnum()]
    return ("".join(letters[:3]) or "GEN").ljust(3, "X")


def table_prefix(table_name: str) -> str:
    return TABLE_PREFIXES.get(table_name) or fallback_table_prefix(table_name)


def is_valid_device_id(value: str | None) -> bool:
    return bool(value) and bool(DEVICE_ID_PATTERN.match(value))


def new_device_id() -> str:
    """A fresh random 6-char alphanumeric device id (uniqueness checked by caller)."""
    return "".join(secrets.choice(DEVICE_ID_ALPHABET) for _ in range(DEVICE_ID_LENGTH))


def build_record_identifier(
    source_prefix: str, device_id: str, table_name: str, count: int
) -> str:
    """Assemble the composite identifier from its four parts."""
    return (
        f"{source_prefix}{device_id}{table_prefix(table_name)}"
        f"{count:0{RECORD_COUNT_WIDTH}d}"
    )
