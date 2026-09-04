"""
services/validation/ndc_cache.py
────────────────────────────────
Cache layer over `services.validation.fda_client.fetch_fda`. Reads from
`medicine_ndc_cache` first; falls back to FDA + UPSERTs on miss.

Cache hits include cached NOT_FOUND rows — important so we don't re-hit
FDA for the ~5 % of dispensed items that are medical devices (not in the
FDA Drug NDC Directory).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models import MedicineNdcCache
from services.validation.fda_client import fetch_fda


async def get_or_fetch(
    session: AsyncSession, ndc11: str, *, force: bool = False
) -> MedicineNdcCache | None:
    if not ndc11:
        return None

    row = await session.get(MedicineNdcCache, ndc11)
    if (
        row
        and not force
        and not settings.NDC_CACHE_FORCE_REFRESH
        and (datetime.utcnow() - row.updated_at) < timedelta(days=settings.NDC_CACHE_TTL_DAYS)
    ):
        return row

    data = await fetch_fda(ndc11)
    stmt = mysql_insert(MedicineNdcCache).values(**data)
    stmt = stmt.on_duplicate_key_update(
        matched_package_ndc=stmt.inserted.matched_package_ndc,
        brand_name=stmt.inserted.brand_name,
        generic_name=stmt.inserted.generic_name,
        dosage_form=stmt.inserted.dosage_form,
        route=stmt.inserted.route,
        marketing_category=stmt.inserted.marketing_category,
        marketing_start_date=stmt.inserted.marketing_start_date,
        marketing_end_date=stmt.inserted.marketing_end_date,
        listing_expiration_date=stmt.inserted.listing_expiration_date,
        package_description=stmt.inserted.package_description,
        is_unit_of_use=stmt.inserted.is_unit_of_use,
        found_in_fda=stmt.inserted.found_in_fda,
        raw_payload=stmt.inserted.raw_payload,
        labeler_name=stmt.inserted.labeler_name,
        strength_text=stmt.inserted.strength_text,
        pack_size_qty=stmt.inserted.pack_size_qty,
        pack_size_uom=stmt.inserted.pack_size_uom,
    )
    await session.execute(stmt)
    await session.commit()
    logger.info(
        "NDC cache {hit}: ndc11={n} found_in_fda={f}",
        hit="REFRESH" if row else "MISS",
        n=ndc11,
        f=data["found_in_fda"],
    )
    return await session.get(MedicineNdcCache, ndc11)
