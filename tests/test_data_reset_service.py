"""Item 4 — RESET DATA soft-deletes every pharmacy-scoped table.

`reset_pharmacy_data` is tested against a fake AsyncSession that records
each `update()` statement's target table and returns a controllable
rowcount, so this verifies the exact set of tables touched (and that
`MedicineNdcCache` — global, not pharmacy-scoped — is correctly excluded)
without needing a real database.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

os.environ.setdefault("FRONTEND_URL", "http://localhost")
os.environ.setdefault("DATABASE_URL", "mysql+asyncmy://root:root@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-only-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")

from services.data_reset_service import reset_pharmacy_data


class _FakeExecuteResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeSession:
    def __init__(self) -> None:
        self.executed_tables: list[str] = []
        self.executed_values: list[dict] = []

    async def execute(self, stmt):
        # `stmt` is a SQLAlchemy Core `Update` construct built by
        # `update(Model).where(...).values(...)` — `.table.name` gives us
        # the real target table without needing a live connection.
        self.executed_tables.append(stmt.table.name)
        # `stmt._values` is an immutabledict of {Column: BindParameter} for
        # an ORM-mapped `update(Model)` construct; unwrap the Column's
        # `.key` (its name) and the BindParameter's `.value`.
        compiled_params = {k.key: v.value for k, v in stmt._values.items()}
        self.executed_values.append(compiled_params)
        return _FakeExecuteResult(rowcount=3)


def test_reset_touches_exactly_the_pharmacy_scoped_tables_in_child_first_order() -> None:
    session = _FakeSession()
    asyncio.run(reset_pharmacy_data(session, ph_id=42))

    assert session.executed_tables == [
        "dispenses",
        "medicines",
        "drug_reports",
        "invoice_line_items",
        "invoice_summaries",
        "invoices",
        "medicine_inventory",
        "documents",
    ]
    # `medicine_ndc_cache` (global, shared FDA cache — no medical_store_id)
    # must never appear.
    assert "medicine_ndc_cache" not in session.executed_tables


def test_reset_returns_rowcount_per_table() -> None:
    session = _FakeSession()
    counts = asyncio.run(reset_pharmacy_data(session, ph_id=42))

    assert counts == {
        "dispenses_deleted": 3,
        "medicines_deleted": 3,
        "drug_reports_deleted": 3,
        "invoice_line_items_deleted": 3,
        "invoice_summaries_deleted": 3,
        "invoices_deleted": 3,
        "inventory_rows_deleted": 3,
        "documents_deleted": 3,
    }


def test_reset_explicitly_stamps_delete_date_at_on_every_statement() -> None:
    """Bulk update() bypasses the ORM before_flush hook that normally
    auto-stamps delete_date_at, so each statement must set it by hand."""
    session = _FakeSession()
    asyncio.run(reset_pharmacy_data(session, ph_id=42))

    for params in session.executed_values:
        assert params.get("IsDeleted") is True
        assert isinstance(params.get("delete_date_at"), datetime)
