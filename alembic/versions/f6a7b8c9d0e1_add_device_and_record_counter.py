"""add device + record_counter tables and make record_Identifier unique

Backs the switch to **server-generated** ``record_Identifier`` sync keys:

  - ``device``          — one row per client device; pins the per-device
                          ``source_prefix`` (e.g. AN001) used to build ids.
  - ``record_counter``  — monotonic counter per (device_id, table_name).
  - seeds the ``WEB000`` sentinel device for web / server-side writes.
  - swaps the non-unique ``ix_<t>_record_Identifier`` index for a UNIQUE one
    on every AuditMixin table. NULLs stay allowed (MySQL permits many), so
    legacy / web rows that never got an id keep working; server-generated ids
    are guaranteed collision-free.

Every step is **idempotent** (guarded by an inspector check) so a re-run after
a partially-applied attempt — e.g. ``device`` created but a later step failed —
completes cleanly instead of erroring on the objects already present.

If it fails on the unique swap, an existing table already holds duplicate
non-NULL record_Identifier values (stale client-supplied test data); dedupe or
NULL them, then re-run.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# AuditMixin tables whose record_Identifier is now server-generated + unique.
TABLES: list[str] = [
    "user",
    "refresh_tokens",
    "medical_store",
    "drug_reports",
    "medicines",
    "dispenses",
    "invoices",
    "invoice_line_items",
    "invoice_summaries",
    "medicine_inventory",
    "medicine_ndc_cache",
    "documents",
    "activity_log",
]


def _tables(insp) -> set[str]:
    return set(insp.get_table_names())


def _indexes(insp, table: str) -> dict:
    return {i["name"]: i for i in insp.get_indexes(table)}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    existing_tables = _tables(insp)

    if "device" not in existing_tables:
        op.create_table(
            "device",
            sa.Column("device_id", sa.String(length=16), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("user.user_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("source_prefix", sa.String(length=16), nullable=False, server_default="AN001"),
            sa.Column("source_platform", sa.String(length=32), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column(
                "last_seen_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            ),
        )
    if "ix_device_user_id" not in _indexes(insp, "device"):
        op.create_index(op.f("ix_device_user_id"), "device", ["user_id"], unique=False)

    if "record_counter" not in existing_tables:
        op.create_table(
            "record_counter",
            sa.Column("device_id", sa.String(length=16), primary_key=True),
            sa.Column("table_name", sa.String(length=64), primary_key=True),
            sa.Column("last_count", sa.BigInteger(), nullable=False, server_default="0"),
        )

    # Sentinel device for web / server-side writes (INSERT IGNORE = no-op if present).
    op.execute(
        "INSERT IGNORE INTO device (device_id, source_prefix, source_platform) "
        "VALUES ('WEB000', 'AN001', 'web')"
    )

    # Non-unique index → unique index on record_Identifier for every table.
    for table in TABLES:
        name = op.f(f"ix_{table}_record_Identifier")
        idxs = _indexes(insp, table)
        current = idxs.get(name)
        if current is None:
            op.create_index(name, table, ["record_Identifier"], unique=True)
        elif not current.get("unique"):
            op.drop_index(name, table_name=table)
            op.create_index(name, table, ["record_Identifier"], unique=True)
        # else: already unique — nothing to do.


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())

    for table in TABLES:
        name = op.f(f"ix_{table}_record_Identifier")
        idxs = _indexes(insp, table)
        if name in idxs:
            op.drop_index(name, table_name=table)
        op.create_index(name, table, ["record_Identifier"], unique=False)

    existing_tables = _tables(insp)
    if "record_counter" in existing_tables:
        op.drop_table("record_counter")
    if "device" in existing_tables:
        op.drop_table("device")
