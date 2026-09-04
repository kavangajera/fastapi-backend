"""
services/ndc_search_service.py
────────────────────────────────
Standalone "enter an NDC, check with FDA" lookup — separate from the
dispense-validation flow. Reuses the same cache/FDA plumbing tier2 uses
(`services/validation/ndc_cache.get_or_fetch`), so a search here also warms
the cache for a subsequent dispense-validate call on the same NDC.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.ndc_search import NdcSearchResponse
from services.ndc_utils import to_ndc11
from services.validation.date_utils import parse_yyyymmdd
from services.validation.ndc_cache import get_or_fetch


async def search_ndc(db: AsyncSession, ndc_raw: str) -> NdcSearchResponse:
    # `to_ndc11` already handles an already-11-digit input (with or without
    # hyphens) as well as a hyphenated 10-digit NDC10 — never guesses.
    ndc11 = to_ndc11((ndc_raw or "").strip())

    if not ndc11:
        return NdcSearchResponse(
            ndc=ndc_raw,
            found_in_fda=False,
            active=None,
            message="Not a valid 11-digit NDC.",
        )

    cache_row = await get_or_fetch(db, ndc11)
    if cache_row is None or not cache_row.found_in_fda:
        return NdcSearchResponse(
            ndc=ndc11,
            found_in_fda=False,
            active=None,
            message=(
                "No FDA record found for this NDC — verify the number, or "
                "this may be a medical device/supply rather than a drug."
            ),
        )

    end_dt = parse_yyyymmdd(cache_row.marketing_end_date)
    today = datetime.utcnow().date()
    is_active = not (end_dt and end_dt < today)

    return NdcSearchResponse(
        ndc=ndc11,
        found_in_fda=True,
        active=is_active,
        brand_name=cache_row.brand_name,
        generic_name=cache_row.generic_name,
        dosage_form=cache_row.dosage_form,
        marketing_end_date=cache_row.marketing_end_date,
        message=(
            "Active with the FDA."
            if is_active
            else f"Discontinued (FDA end date {cache_row.marketing_end_date})."
        ),
    )
