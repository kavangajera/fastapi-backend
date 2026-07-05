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

If this migration fails on the unique swap, an existing table already holds
duplicate non-NULL record_Identifier values (stale client-supplied test data);
dedupe or NULL them, then re-run.

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


def upgrade() -> None:
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
    op.create_index(op.f("ix_device_user_id"), "device", ["user_id"], unique=False)

    op.create_table(
        "record_counter",
        sa.Column("device_id", sa.String(length=16), primary_key=True),
        sa.Column("table_name", sa.String(length=64), primary_key=True),
        sa.Column("last_count", sa.BigInteger(), nullable=False, server_default="0"),
    )

    # Sentinel device for web / server-side writes (no client device session).
    op.execute(
        "INSERT INTO device (device_id, source_prefix, source_platform) "
        "VALUES ('WEB000', 'AN001', 'web')"
    )

    # Non-unique index → unique index on record_Identifier for every table.
    for table in TABLES:
        op.drop_index(op.f(f"ix_{table}_record_Identifier"), table_name=table)
        op.create_index(
            op.f(f"ix_{table}_record_Identifier"),
            table,
            ["record_Identifier"],
            unique=True,
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(op.f(f"ix_{table}_record_Identifier"), table_name=table)
        op.create_index(
            op.f(f"ix_{table}_record_Identifier"),
            table,
            ["record_Identifier"],
            unique=False,
        )

    op.drop_table("record_counter")
    op.drop_index(op.f("ix_device_user_id"), table_name="device")
    op.drop_table("device")
