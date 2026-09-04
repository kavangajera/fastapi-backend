"""Item 3 — standalone NDC search: enter an NDC, hit FDA (via the shared
cache), get back found/active status.

`get_or_fetch` is patched so this never touches a real DB/network — same
approach as the reconciliation/reset tests.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("FRONTEND_URL", "http://localhost")
os.environ.setdefault("DATABASE_URL", "mysql+asyncmy://root:root@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-only-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")

from services.ndc_search_service import search_ndc


def _cache_row(**overrides) -> SimpleNamespace:
    defaults = dict(
        found_in_fda=True,
        brand_name="Vascepa",
        generic_name="icosapent ethyl",
        dosage_form="CAPSULE",
        marketing_end_date=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_invalid_ndc_never_calls_fda() -> None:
    with patch(
        "services.ndc_search_service.get_or_fetch", new_callable=AsyncMock
    ) as mock_get:
        result = asyncio.run(search_ndc(db=None, ndc_raw="garbage"))

    mock_get.assert_not_called()
    assert result.found_in_fda is False
    assert result.active is None
    assert "not a valid" in result.message.lower()


def test_ndc_not_found_in_fda() -> None:
    with patch(
        "services.ndc_search_service.get_or_fetch", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = None
        result = asyncio.run(search_ndc(db=None, ndc_raw="52937-001-20"))

    assert result.found_in_fda is False
    assert result.active is None
    assert "no fda record found" in result.message.lower()


def test_ndc_found_and_active_when_no_marketing_end_date() -> None:
    """Real Vascepa data from this session: no marketing_end_date == active."""
    with patch(
        "services.ndc_search_service.get_or_fetch", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = _cache_row(marketing_end_date=None)
        result = asyncio.run(search_ndc(db=None, ndc_raw="52937-001-20"))

    assert result.found_in_fda is True
    assert result.active is True
    assert result.brand_name == "Vascepa"
    assert "active" in result.message.lower()


def test_ndc_found_but_discontinued_when_end_date_in_the_past() -> None:
    with patch(
        "services.ndc_search_service.get_or_fetch", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = _cache_row(marketing_end_date="20200101")
        result = asyncio.run(search_ndc(db=None, ndc_raw="0169-4132-12"))

    assert result.found_in_fda is True
    assert result.active is False
    assert "discontinued" in result.message.lower()


def test_ndc_found_with_future_end_date_is_still_active() -> None:
    """A future marketing_end_date means 'scheduled to be delisted', not
    'already discontinued' — confirmed via FDA's own docs earlier this
    session."""
    with patch(
        "services.ndc_search_service.get_or_fetch", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = _cache_row(marketing_end_date="20991231")
        result = asyncio.run(search_ndc(db=None, ndc_raw="0378-3458-23"))

    assert result.active is True
