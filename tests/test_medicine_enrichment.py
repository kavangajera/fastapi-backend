"""Item 5 — validate_tier2 surfaces FDA-verified manufacturer/strength/
original pack size per medicine via `ValidationReport.medicine_enrichment`,
alongside (not replacing) the OCR-extracted values.

`get_or_fetch` is patched inside `services.validation.tier2`'s namespace
(that's where it's imported into) so this never touches a real DB/network.
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("FRONTEND_URL", "http://localhost")
os.environ.setdefault("DATABASE_URL", "mysql+asyncmy://root:root@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-only-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")

from services.validation.tier2 import validate_tier2


def _report_data(ndc: str = "11111111111", drug_name: str = "VASCEPA") -> dict:
    return {
        "medicines": [
            {
                "ndc": ndc,
                "drug_name": drug_name,
                "dispenses": [{"rx_no": "1", "qty_disp": "30", "date_filled": "01/01/2026"}],
            }
        ]
    }


def _found_cache_row(**overrides) -> SimpleNamespace:
    defaults = dict(
        found_in_fda=True,
        labeler_name="Amarin Pharma Inc.",
        strength_text="ICOSAPENT ETHYL 1000 mg/1",
        pack_size_qty=Decimal("120"),
        pack_size_uom="CAPSULE",
        dosage_form="CAPSULE",
        brand_name="Vascepa",
        generic_name="icosapent ethyl",
        is_unit_of_use=False,
        marketing_start_date="20121001",
        marketing_end_date=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_enrichment_populated_when_ndc_found() -> None:
    with patch(
        "services.validation.tier2.get_or_fetch", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = _found_cache_row()
        report = asyncio.run(
            validate_tier2(session=None, report_data=_report_data(), granted=None)
        )

    assert len(report.medicine_enrichment) == 1
    e = report.medicine_enrichment[0]
    assert e.found_in_fda is True
    assert e.manufacturer == "Amarin Pharma Inc."
    assert e.strength == "ICOSAPENT ETHYL 1000 mg/1"
    assert e.original_pack_size == "120 CAPSULE"
    assert e.brand_name == "Vascepa"
    assert e.generic_name == "icosapent ethyl"


def test_enrichment_still_populated_when_ndc_not_found() -> None:
    """UI should be able to show 'not found' too, not just successful
    lookups. Shape matches `_normalize_fda`'s "not found" dict: every
    field None except `found_in_fda`."""
    not_found_row = SimpleNamespace(
        found_in_fda=False,
        labeler_name=None,
        strength_text=None,
        pack_size_qty=None,
        pack_size_uom=None,
        dosage_form=None,
        brand_name=None,
        generic_name=None,
    )
    with patch(
        "services.validation.tier2.get_or_fetch", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = not_found_row
        report = asyncio.run(
            validate_tier2(session=None, report_data=_report_data(), granted=None)
        )

    assert len(report.medicine_enrichment) == 1
    e = report.medicine_enrichment[0]
    assert e.found_in_fda is False
    assert e.manufacturer is None
    assert e.original_pack_size is None


def test_enrichment_omits_pack_size_when_not_parsed() -> None:
    with patch(
        "services.validation.tier2.get_or_fetch", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = _found_cache_row(pack_size_qty=None, pack_size_uom=None)
        report = asyncio.run(
            validate_tier2(session=None, report_data=_report_data(), granted=None)
        )

    assert report.medicine_enrichment[0].original_pack_size is None
