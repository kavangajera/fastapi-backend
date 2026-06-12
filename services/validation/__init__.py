"""
services/validation
───────────────────
Drug dispense report validation engine. Spec §7 modules A–H plus the
foundations (NDC normalization, patient key, insurance canonicalizer,
grand-total recompute, field sanity).

Public entry points:
    validate_tier1(report_data)                      → no external calls
    validate_tier2(session, report_data, tier1_report=None)
                                                     → adds FDA-dependent
                                                       alerts A/B/C
"""

from services.validation.tier1 import validate_tier1
from services.validation.tier2 import validate_tier2

__all__ = ["validate_tier1", "validate_tier2"]
