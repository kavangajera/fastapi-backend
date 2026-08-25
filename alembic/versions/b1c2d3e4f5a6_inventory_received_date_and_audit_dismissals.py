"""inventory received_date + audit_dismissals

Two additions, both purely additive:

  - medicine_inventory.received_date (DATE, nullable, indexed)
      When the stock was last received, parsed from the adding invoice's
      printed date (falling back to its upload date). Backs the date-range
      filter on the inventory list. NULL on pre-existing rows and on rows
      only ever touched by a dispense — subtracting stock is not a receipt.

  - audit_dismissals
      Audit-report entries the owner has cleared. The audit report is
      derived from `documents` / `drug_reports` on every request, so
      clearing a row cannot delete anything without destroying the
      compliance record; the dismissal is recorded here and the derived
      rows are filtered against it. Soft-deleting a dismissal restores the
      entry.

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(insp, table: str) -> bool:
    return table in insp.get_table_names()


def _has_column(insp, table: str, column: str) -> bool:
    return _has_table(insp, table) and any(
        c["name"] == column for c in insp.get_columns(table)
    )


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if not _has_column(insp, "medicine_inventory", "received_date"):
        op.add_column(
            "medicine_inventory",
            sa.Column("received_date", sa.Date(), nullable=True),
        )
        op.create_index(
            "ix_medicine_inventory_received_date",
            "medicine_inventory",
            ["received_date"],
        )

    if not _has_table(insp, "audit_dismissals"):
        op.create_table(
            "audit_dismissals",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("medical_store_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=20), nullable=False),
            sa.Column("ref", sa.String(length=64), nullable=False),
            sa.Column("dismissed_by_user_id", sa.Integer(), nullable=True),
            # AuditMixin columns — same shape as every other table.
            sa.Column("record_Identifier", sa.String(length=36), nullable=True),
            sa.Column("update_record_Identifier", sa.String(length=36), nullable=True),
            sa.Column(
                "IsDeleted", sa.Boolean(), server_default=sa.text("0"), nullable=False
            ),
            sa.Column("delete_date_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "global_time_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["medical_store_id"],
                ["medical_store.medical_store_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["dismissed_by_user_id"], ["user.user_id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "medical_store_id", "kind", "ref", name="uq_audit_dismissal_store_kind_ref"
            ),
        )
        op.create_index(
            "ix_audit_dismissals_medical_store_id", "audit_dismissals", ["medical_store_id"]
        )
        op.create_index("ix_audit_dismissals_kind", "audit_dismissals", ["kind"])
        op.create_index("ix_audit_dismissals_ref", "audit_dismissals", ["ref"])
        op.create_index(
            "ix_audit_dismissals_record_Identifier", "audit_dismissals", ["record_Identifier"]
        )
        op.create_index(
            "ix_audit_dismissals_update_record_Identifier",
            "audit_dismissals",
            ["update_record_Identifier"],
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if _has_table(insp, "audit_dismissals"):
        op.drop_table("audit_dismissals")

    if _has_column(insp, "medicine_inventory", "received_date"):
        op.drop_index("ix_medicine_inventory_received_date", table_name="medicine_inventory")
        op.drop_column("medicine_inventory", "received_date")
