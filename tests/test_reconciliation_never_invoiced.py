"""Item 1 — invoice-vs-billed reconciliation gets a distinct NEVER_INVOICED
status ("No Invoice Record Found") instead of being lumped into
OVER_BILLED.

`_status` is tested as a pure function. `invoice_vs_billed` is tested
against a fake AsyncSession (no real DB) whose `execute()` returns
pre-built rows shaped exactly like the two queries the service issues.
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

os.environ.setdefault("FRONTEND_URL", "http://localhost")
os.environ.setdefault("DATABASE_URL", "mysql+asyncmy://root:root@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-only-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")

from services.reconciliation_service import (
    STATUS_MATCHED,
    STATUS_NEVER_INVOICED,
    STATUS_OVER_BILLED,
    STATUS_UNDER_DISPENSED,
    _status,
    invoice_vs_billed,
)

# ── Pure `_status` ────────────────────────────────────────────────────────


def test_status_never_invoiced_when_no_invoice_line_item_exists() -> None:
    # Even with invoiced=0 and dispensed=0, "never invoiced" wins first.
    assert _status(Decimal("0"), Decimal("0"), ever_invoiced=False) == STATUS_NEVER_INVOICED
    assert _status(Decimal("0"), Decimal("30"), ever_invoiced=False) == STATUS_NEVER_INVOICED


def test_status_over_billed_only_when_ever_invoiced() -> None:
    assert _status(Decimal("10"), Decimal("30"), ever_invoiced=True) == STATUS_OVER_BILLED


def test_status_under_dispensed_and_matched() -> None:
    assert _status(Decimal("30"), Decimal("10"), ever_invoiced=True) == STATUS_UNDER_DISPENSED
    assert _status(Decimal("30"), Decimal("30"), ever_invoiced=True) == STATUS_MATCHED


# ── `invoice_vs_billed` against a fake session ────────────────────────────


class _FakeResult:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class _FakeSession:
    """Returns the dispensed-qty rows on the first execute() call, the
    invoiced-qty rows on the second — matching the two queries
    `invoice_vs_billed` issues, in that order."""

    def __init__(self, disp_rows: list[tuple], inv_rows: list[tuple]) -> None:
        self._disp_rows = disp_rows
        self._inv_rows = inv_rows
        self._calls = 0

    async def execute(self, _stmt):
        self._calls += 1
        return _FakeResult(self._disp_rows if self._calls == 1 else self._inv_rows)


def test_ndc_dispensed_but_never_invoiced_reports_no_invoice_record_found() -> None:
    session = _FakeSession(
        disp_rows=[("11111111111", Decimal("30"), "DRUG A")],
        inv_rows=[],  # nothing ever invoiced
    )
    rows, summary = asyncio.run(invoice_vs_billed(session, medical_store_id=1))

    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == STATUS_NEVER_INVOICED
    assert row["message"] == (
        "No Invoice Record Found — upload the invoice that brought this drug in, "
        "or verify the NDC."
    )
    assert summary["never_invoiced"] == 1
    assert summary["over_billed"] == 0


def test_matched_row_has_no_message() -> None:
    session = _FakeSession(
        disp_rows=[("11111111111", Decimal("30"), "DRUG A")],
        inv_rows=[("11111111111", "30", "DRUG A")],
    )
    rows, summary = asyncio.run(invoice_vs_billed(session, medical_store_id=1))

    assert rows[0]["status"] == STATUS_MATCHED
    assert rows[0]["message"] is None
    assert summary["matched"] == 1
    assert summary["never_invoiced"] == 0


def test_never_invoiced_sorts_ahead_of_over_billed() -> None:
    session = _FakeSession(
        disp_rows=[
            ("11111111111", Decimal("30"), "NEVER INVOICED DRUG"),
            ("22222222222", Decimal("100"), "OVER BILLED DRUG"),
        ],
        inv_rows=[("22222222222", "10", "OVER BILLED DRUG")],
    )
    rows, _ = asyncio.run(invoice_vs_billed(session, medical_store_id=1))

    assert rows[0]["status"] == STATUS_NEVER_INVOICED
    assert rows[1]["status"] == STATUS_OVER_BILLED
