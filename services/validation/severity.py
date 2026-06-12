"""
services/validation/severity.py
───────────────────────────────
Helpers around the Severity literal so the rest of the engine doesn't
keep open-coding string literals. Severity is defined in schemas.validation
to keep the OpenAPI source single-of-truth.
"""

from __future__ import annotations

from schemas.validation import (
    Alert,
    GrandTotalRecompute,
    PerPatientTotal,
    Severity,
    ValidationReport,
    ValidationSummary,
)


def summarize(alerts: list[Alert], *, tier1: bool, tier2: bool) -> ValidationSummary:
    counts = {"ERROR": 0, "WARNING": 0, "INFO": 0, "INDETERMINATE": 0, "PASS": 0}
    for a in alerts:
        counts[a.severity] = counts.get(a.severity, 0) + 1
    return ValidationSummary(
        errors=counts["ERROR"],
        warnings=counts["WARNING"],
        info=counts["INFO"],
        indeterminate=counts["INDETERMINATE"],
        blocking=counts["ERROR"] > 0,
        tier1_ran=tier1,
        tier2_ran=tier2,
    )


__all__ = [
    "Alert",
    "Severity",
    "ValidationReport",
    "ValidationSummary",
    "GrandTotalRecompute",
    "PerPatientTotal",
    "summarize",
]
