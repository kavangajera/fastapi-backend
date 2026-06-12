"""
models/medicine_ndc_cache.py
────────────────────────────
Per-NDC cache of FDA Drug NDC Directory lookups.

Why: live FDA calls take 1–2 s each (and sometimes 3 retries to land on the
right NDC10 segmentation). An 85-medicine dispense report = ~100–180 s of
HTTP. Cache that on first lookup, key on `ndc11`, and the second submit of
the same medicines runs in well under a second.

`found_in_fda=False` is also cached (otherwise we'd re-hit FDA on every
submit for medical devices / lancets / sensors that aren't in the Drug NDC
Directory at all).
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from core.async_db import Base


class MedicineNdcCache(Base):
    __tablename__ = "medicine_ndc_cache"

    ndc11: Mapped[str] = mapped_column(String(11), primary_key=True)
    matched_package_ndc: Mapped[str | None] = mapped_column(String(20), nullable=True)

    brand_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generic_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dosage_form: Mapped[str | None] = mapped_column(String(100), nullable=True)
    route: Mapped[str | None] = mapped_column(String(100), nullable=True)
    marketing_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    marketing_start_date: Mapped[str | None] = mapped_column(String(8), nullable=True)
    marketing_end_date: Mapped[str | None] = mapped_column(String(8), nullable=True)
    listing_expiration_date: Mapped[str | None] = mapped_column(String(8), nullable=True)

    package_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_unit_of_use: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    found_in_fda: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    raw_payload: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
