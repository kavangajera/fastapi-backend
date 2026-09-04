"""Item 6 — real numeric pack-size parsing from FDA `package_description`,
and Module C reconciling `qty_disp` against it (falling back to the old
whole-number-of-packages check when parsing is inconclusive).

All pure-function tests: `parse_pack_size` takes a string, `_module_c`
takes a fake cache_row (SimpleNamespace) — no DB, no network.
"""

from __future__ import annotations

import os
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("FRONTEND_URL", "http://localhost")
os.environ.setdefault("DATABASE_URL", "mysql+asyncmy://root:root@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-only-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")

from schemas.validation import Alert
from services.validation.fda_client import parse_pack_size
from services.validation.tier2 import _module_c

# ── parse_pack_size ────────────────────────────────────────────────────────


def test_parses_simple_package_description() -> None:
    """Real FDA data sampled this session: azelastine/fluticasone nasal
    spray, NDC 0378-3458-23."""
    result = parse_pack_size("1 BOTTLE in 1 BOX (0378-3458-23)  / 120 SPRAY, METERED in 1 BOTTLE")
    assert result == (Decimal("120"), "SPRAY, METERED")


def test_parses_compound_injectable_description_using_last_segment() -> None:
    """Real FDA data sampled this session: Mounjaro single-dose vial,
    NDC 0002-1152-01 — the LAST segment (fill quantity per vial) is what
    qty_disp should reconcile against, not the outer-carton count."""
    result = parse_pack_size(
        "1 VIAL, SINGLE-DOSE in 1 CARTON (0002-1152-01)  / .5 mL in 1 VIAL, SINGLE-DOSE"
    )
    assert result == (Decimal("0.5"), "mL")


def test_returns_none_for_missing_description() -> None:
    assert parse_pack_size(None) is None
    assert parse_pack_size("") is None


def test_returns_none_for_unrecognized_shape() -> None:
    assert parse_pack_size("some random text with no numbers") is None


def test_returns_none_for_zero_or_negative_quantity() -> None:
    assert parse_pack_size("0 TABLET in 1 BOTTLE") is None


# ── Module C ────────────────────────────────────────────────────────────


def _cache_row(**overrides) -> SimpleNamespace:
    defaults = dict(
        found_in_fda=True,
        is_unit_of_use=True,
        dosage_form="SPRAY, METERED",
        pack_size_qty=None,
        pack_size_uom=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_bulk_products_are_never_checked() -> None:
    cache_row = _cache_row(is_unit_of_use=False)
    alerts: list[Alert] = []
    _module_c(
        mi=0,
        ndc11="11111111111",
        med={"dispenses": [{"qty_disp": "1.5", "rx_no": "1"}]},
        cache_row=cache_row,
        alerts=alerts,
    )
    assert alerts == []


def test_whole_multiple_of_real_pack_size_passes() -> None:
    cache_row = _cache_row(pack_size_qty=Decimal("120"), pack_size_uom="SPRAY, METERED")
    alerts: list[Alert] = []
    _module_c(
        mi=0,
        ndc11="11111111111",
        med={"dispenses": [{"qty_disp": "240", "rx_no": "1"}]},
        cache_row=cache_row,
        alerts=alerts,
    )
    assert alerts == []


def test_non_whole_multiple_of_real_pack_size_flags_error() -> None:
    cache_row = _cache_row(pack_size_qty=Decimal("120"), pack_size_uom="SPRAY, METERED")
    alerts: list[Alert] = []
    _module_c(
        mi=0,
        ndc11="11111111111",
        med={"dispenses": [{"qty_disp": "130", "rx_no": "1"}]},
        cache_row=cache_row,
        alerts=alerts,
    )
    assert len(alerts) == 1
    assert alerts[0].code == "PACK_SIZE_NOT_WHOLE_MULTIPLE"
    assert alerts[0].severity == "ERROR"
    assert "120" in alerts[0].expected


def test_non_integer_pack_size_reconciles_correctly() -> None:
    """8.5 mL vial: qty_disp=17 (2 vials worth) must pass; 10 must fail."""
    cache_row = _cache_row(pack_size_qty=Decimal("8.5"), pack_size_uom="mL")
    alerts: list[Alert] = []
    _module_c(
        mi=0,
        ndc11="11111111111",
        med={
            "dispenses": [
                {"qty_disp": "17", "rx_no": "1"},
                {"qty_disp": "10", "rx_no": "2"},
            ]
        },
        cache_row=cache_row,
        alerts=alerts,
    )
    assert len(alerts) == 1
    assert alerts[0].rx_no == "2"


def test_falls_back_to_whole_number_check_when_pack_size_unparseable() -> None:
    """No confidently-parsed pack size for this NDC — old behavior must be
    unchanged: any non-integer qty_disp is flagged."""
    cache_row = _cache_row(pack_size_qty=None, pack_size_uom=None)
    alerts: list[Alert] = []
    _module_c(
        mi=0,
        ndc11="11111111111",
        med={"dispenses": [{"qty_disp": "1.5", "rx_no": "1"}]},
        cache_row=cache_row,
        alerts=alerts,
    )
    assert len(alerts) == 1
    assert alerts[0].code == "UNIT_OF_USE_FRACTIONAL"


def test_fallback_path_accepts_whole_numbers() -> None:
    cache_row = _cache_row(pack_size_qty=None, pack_size_uom=None)
    alerts: list[Alert] = []
    _module_c(
        mi=0,
        ndc11="11111111111",
        med={"dispenses": [{"qty_disp": "2", "rx_no": "1"}]},
        cache_row=cache_row,
        alerts=alerts,
    )
    assert alerts == []
