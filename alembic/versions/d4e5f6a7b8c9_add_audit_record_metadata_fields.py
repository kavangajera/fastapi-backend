"""add audit / record-metadata fields to every table

Adds the shared ``AuditMixin`` columns (defined in ``core/async_db.py``)
to every existing table:

  - record_Identifier         VARCHAR(36)  indexed, nullable — client-generated sync key
  - update_record_Identifier  VARCHAR(36)  indexed, nullable — client-generated edit key
  - IsDeleted                 BOOLEAN               — soft-delete flag (default 0)
  - created_at                DATETIME              — row creation time (UTC)
  - updated_at                DATETIME              — last update time (UTC, ON UPDATE)
  - global_time_at            DATETIME              — UTC "global clock" mirror of updated_at

Tables that already had ``created_at`` / ``updated_at`` keep their existing
column and only gain the columns they were missing.
``record_Identifier`` / ``update_record_Identifier`` are optional,
client-supplied (mobile-app) sync keys: nullable + indexed, NOT unique,
never server-generated, so legacy and web-created rows that omit them
keep working.

Revision ID: d4e5f6a7b8c9
Revises: b7e1a2c3d4f5
Create Date: 2026-06-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'b7e1a2c3d4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Every table that maps to an ORM model.
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

# created_at / updated_at columns that already exist per table — skip these
# so we don't duplicate (or clobber) the pre-existing definitions.
EXISTING_TIMESTAMPS: dict[str, set[str]] = {
    "drug_reports": {"created_at"},
    "invoices": {"created_at"},
    "medicine_inventory": {"created_at", "updated_at"},
    "medicine_ndc_cache": {"updated_at"},
    "documents": {"created_at", "updated_at"},
    "activity_log": {"created_at"},
}

_CURRENT_TS = sa.text("CURRENT_TIMESTAMP")
_CURRENT_TS_ON_UPDATE = sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")


def upgrade() -> None:
    for table in TABLES:
        existing = EXISTING_TIMESTAMPS.get(table, set())

        # record_Identifier / update_record_Identifier: optional, client-generated
        # sync keys. Nullable + indexed (NOT unique, no back-fill) so legacy rows
        # and web-created rows that omit them keep working.
        op.add_column(table, sa.Column("record_Identifier", sa.String(length=36), nullable=True))
        op.create_index(
            op.f(f"ix_{table}_record_Identifier"),
            table,
            ["record_Identifier"],
            unique=False,
        )
        op.add_column(
            table, sa.Column("update_record_Identifier", sa.String(length=36), nullable=True)
        )
        op.create_index(
            op.f(f"ix_{table}_update_record_Identifier"),
            table,
            ["update_record_Identifier"],
            unique=False,
        )

        # IsDeleted: existing rows default to 0 (not deleted).
        op.add_column(
            table,
            sa.Column("IsDeleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )

        # created_at / updated_at: only where the table didn't already have them.
        if "created_at" not in existing:
            op.add_column(
                table,
                sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_CURRENT_TS),
            )
        if "updated_at" not in existing:
            op.add_column(
                table,
                sa.Column(
                    "updated_at",
                    sa.DateTime(),
                    nullable=False,
                    server_default=_CURRENT_TS_ON_UPDATE,
                ),
            )

        # global_time_at: always new.
        op.add_column(
            table,
            sa.Column(
                "global_time_at",
                sa.DateTime(),
                nullable=False,
                server_default=_CURRENT_TS_ON_UPDATE,
            ),
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        existing = EXISTING_TIMESTAMPS.get(table, set())

        op.drop_column(table, "global_time_at")
        if "updated_at" not in existing:
            op.drop_column(table, "updated_at")
        if "created_at" not in existing:
            op.drop_column(table, "created_at")
        op.drop_column(table, "IsDeleted")
        op.drop_index(op.f(f"ix_{table}_update_record_Identifier"), table_name=table)
        op.drop_column(table, "update_record_Identifier")
        op.drop_index(op.f(f"ix_{table}_record_Identifier"), table_name=table)
        op.drop_column(table, "record_Identifier")
