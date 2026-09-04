"""Item 7 — per-report `disabled_modules` opt-out, independent of plan
gating. Covers: the schema validator, tier1's per-module suppression
(including PLAN_LOCKED markers), and tier2's A/B/C + module-D suppression.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

os.environ.setdefault("FRONTEND_URL", "http://localhost")
os.environ.setdefault("DATABASE_URL", "mysql+asyncmy://root:root@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-only-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")

from schemas.save_dispense import DispenseSaveRequest
from services.validation.tier1 import validate_tier1
from services.validation.tier2 import validate_tier2

# ── Schema validator ──────────────────────────────────────────────────────


def _save_request(disabled_modules) -> dict:
    return {
        "medical_store_id": 1,
        "disabled_modules": disabled_modules,
        "medicines": [{"drug_name": "X", "ndc": "11111111111", "dispenses": []}],
    }


def test_known_module_letters_are_accepted() -> None:
    req = DispenseSaveRequest.model_validate(_save_request(["C", "G"]))
    assert req.disabled_modules == ["C", "G"]


def test_unknown_module_letter_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DispenseSaveRequest.model_validate(_save_request(["Z"]))


def test_field_sanity_cannot_be_disabled() -> None:
    """FIELD ERRORs protect the inventory-subtraction math on save —
    excluded from the disablable set on purpose."""
    with pytest.raises(ValidationError):
        DispenseSaveRequest.model_validate(_save_request(["FIELD"]))


# ── tier1: module D suppressed, including its PLAN_LOCKED marker ─────────


def _report_with_bad_days_supply() -> dict:
    return {
        "medicines": [
            {
                "ndc": "11111111111",
                "drug_name": "X",
                "dispenses": [{"rx_no": "1", "days_supply": "0", "qty_disp": "30"}],
            }
        ]
    }


def test_disabled_module_d_suppresses_its_alert() -> None:
    report = validate_tier1(
        _report_with_bad_days_supply(), granted=None, disabled_modules={"D"}
    )
    codes = [a.code for a in report.alerts]
    assert "DAYS_SUPPLY_INVALID" not in codes


def test_module_d_still_fires_when_not_disabled() -> None:
    report = validate_tier1(_report_with_bad_days_supply(), granted=None, disabled_modules=set())
    codes = [a.code for a in report.alerts]
    assert "DAYS_SUPPLY_INVALID" in codes


def test_disabled_module_suppresses_plan_locked_marker_too() -> None:
    """A user who disabled a category shouldn't get nagged to upgrade for it."""
    report = validate_tier1(
        _report_with_bad_days_supply(), granted=set(), disabled_modules={"D"}
    )
    plan_locked_modules = [a.module for a in report.alerts if a.code == "PLAN_LOCKED"]
    assert "D" not in plan_locked_modules


def test_plan_locked_marker_still_fires_when_not_disabled() -> None:
    report = validate_tier1(
        _report_with_bad_days_supply(), granted=set(), disabled_modules=set()
    )
    plan_locked_modules = [a.module for a in report.alerts if a.code == "PLAN_LOCKED"]
    assert "D" in plan_locked_modules


def test_module_g_totals_still_computed_when_alerts_disabled() -> None:
    """Disabling 'G' suppresses the alert noise but the totals themselves
    must still be returned."""
    dispenses = [{"rx_no": "1", "price": "1000000", "ins_paid": "0", "qty_disp": "1"}]
    report_data = {
        "medicines": [{"ndc": "11111111111", "drug_name": "X", "dispenses": dispenses}],
        "grand_total": {"total_price": "0"},  # forces a GRAND_TOTAL_DELTA_PRICE mismatch
    }
    report = validate_tier1(report_data, granted=None, disabled_modules={"G"})

    codes = [a.code for a in report.alerts]
    assert "GRAND_TOTAL_DELTA_PRICE" not in codes
    assert "UNPAID_LINE" not in codes
    # But the recomputed totals are still present.
    assert report.grand_total is not None
    assert report.grand_total.recomputed_sum_price == "1000000"


# ── tier2: modules A/B/C and module D suppressed ──────────────────────────


def _cache_row_fractional_unit_of_use() -> SimpleNamespace:
    return SimpleNamespace(
        found_in_fda=True,
        is_unit_of_use=True,
        dosage_form="SPRAY, METERED",
        pack_size_qty=None,
        pack_size_uom=None,
        brand_name="X",
        generic_name="X",
        marketing_start_date=None,
        marketing_end_date=None,
        labeler_name=None,
        strength_text=None,
    )


def _report_data() -> dict:
    return {
        "medicines": [
            {
                "ndc": "11111111111",
                "drug_name": "X",
                "dispenses": [
                    {"rx_no": "1", "qty_disp": "1.5", "days_supply": "1000", "date_filled": "01/01/2026"}
                ],
            }
        ]
    }


def test_disabled_module_c_suppresses_pack_size_alert() -> None:
    with patch(
        "services.validation.tier2.get_or_fetch", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = _cache_row_fractional_unit_of_use()
        report = asyncio.run(
            validate_tier2(
                session=None, report_data=_report_data(), granted=None, disabled_modules={"C"}
            )
        )

    codes = [a.code for a in report.alerts]
    assert "UNIT_OF_USE_FRACTIONAL" not in codes
    assert "PACK_SIZE_NOT_WHOLE_MULTIPLE" not in codes
    # Granted (plan allows it), just user-disabled -> no upsell nag either.
    plan_locked_modules = [a.module for a in report.alerts if a.code == "PLAN_LOCKED"]
    assert "C" not in plan_locked_modules


def test_module_c_still_fires_when_not_disabled() -> None:
    with patch(
        "services.validation.tier2.get_or_fetch", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = _cache_row_fractional_unit_of_use()
        report = asyncio.run(
            validate_tier2(session=None, report_data=_report_data(), granted=None)
        )

    codes = [a.code for a in report.alerts]
    assert "UNIT_OF_USE_FRACTIONAL" in codes


def test_disabled_module_d_suppresses_fractional_daily_dose() -> None:
    """tier2's own Module D (FRACTIONAL_DAILY_DOSE) is gated by the same
    'D' letter as tier1's days-supply module."""
    report_data = {
        "medicines": [
            {
                "ndc": "11111111111",
                "drug_name": "X",
                "dispenses": [{"rx_no": "1", "qty_disp": "10", "days_supply": "3"}],
            }
        ]
    }
    with patch(
        "services.validation.tier2.get_or_fetch", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = SimpleNamespace(
            found_in_fda=False,
            labeler_name=None,
            strength_text=None,
            pack_size_qty=None,
            pack_size_uom=None,
            dosage_form=None,
            brand_name=None,
            generic_name=None,
        )
        report = asyncio.run(
            validate_tier2(
                session=None, report_data=report_data, granted=None, disabled_modules={"D"}
            )
        )

    codes = [a.code for a in report.alerts]
    assert "FRACTIONAL_DAILY_DOSE" not in codes
