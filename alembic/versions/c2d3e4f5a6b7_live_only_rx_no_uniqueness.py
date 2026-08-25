"""rx_no uniqueness applies to live dispenses only

`uq_dispenses_store_rx_no` was UNIQUE(medical_store_id, rx_no), which keeps
reserving the rx_no of a SOFT-DELETED dispense. Deleting a dispense report
and re-uploading the corrected version therefore failed with a duplicate-key
IntegrityError — and the app-level pre-check in routes/dispense_save.py
filters `IsDeleted`, so it waved the insert through to that raw 500.

MySQL has no partial indexes, so this uses the standard workaround: a stored
generated column holding the rx_no while the row is live and NULL once it is
deleted. MySQL permits unlimited NULLs in a unique index, so any number of
deleted rows may share an rx_no while live ones stay unique per pharmacy.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "dispenses"
OLD_UQ = "uq_dispenses_store_rx_no"
NEW_UQ = "uq_dispenses_store_rx_no_active"


def _has_column(insp, table: str, column: str) -> bool:
    return any(c["name"] == column for c in insp.get_columns(table))


def _has_constraint(insp, table: str, name: str) -> bool:
    if any(c["name"] == name for c in insp.get_unique_constraints(table)):
        return True
    # MySQL surfaces a unique constraint as an index too, depending on how it
    # was created — check both so a re-run is genuinely idempotent.
    return any(i["name"] == name for i in insp.get_indexes(table))


def _drop_unique(insp, table: str, name: str) -> None:
    if any(c["name"] == name for c in insp.get_unique_constraints(table)):
        op.drop_constraint(name, table, type_="unique")
    elif any(i["name"] == name for i in insp.get_indexes(table)):
        op.drop_index(name, table_name=table)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if not _has_column(insp, TABLE, "rx_no_active"):
        # STORED (not VIRTUAL): a unique index over a generated column
        # requires it to be persisted on MySQL.
        op.execute(
            f"ALTER TABLE `{TABLE}` "
            "ADD COLUMN `rx_no_active` VARCHAR(20) "
            "GENERATED ALWAYS AS (IF(`IsDeleted` = 0, `rx_no`, NULL)) STORED"
        )

    # Order matters: the new key must exist before the old one is dropped, so
    # the table is never briefly unprotected against duplicate live rx_nos.
    if not _has_constraint(insp, TABLE, NEW_UQ):
        op.create_unique_constraint(NEW_UQ, TABLE, ["medical_store_id", "rx_no_active"])

    _drop_unique(insp, TABLE, OLD_UQ)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())

    # Restoring the old key can fail if soft-deleted rows now share an rx_no
    # with a live one — exactly the situation this revision exists to allow.
    # Recreate it first so the failure is loud rather than silently leaving
    # the table with no uniqueness at all.
    if not _has_constraint(insp, TABLE, OLD_UQ):
        op.create_unique_constraint(OLD_UQ, TABLE, ["medical_store_id", "rx_no"])

    _drop_unique(insp, TABLE, NEW_UQ)

    if _has_column(insp, TABLE, "rx_no_active"):
        op.drop_column(TABLE, "rx_no_active")
