"""reconcile refill_dismissals with the full AuditMixin column set

``refill_dismissals`` was created in ``b7e1a2c3d4f5`` with only
``created_at`` from the audit set, and the later blanket audit migration
(``d4e5f6a7b8c9``) excluded it — yet the ORM model is
``RefillDismissal(AuditMixin, Base)``. The model therefore expects
``record_Identifier`` / ``update_record_Identifier`` / ``IsDeleted`` /
``updated_at`` / ``global_time_at`` / ``delete_date_at`` columns the table
never got, so the auto-injected ``WHERE IsDeleted = False`` soft-delete filter
(and any ORM read) breaks against it.

This migration adds whatever AuditMixin columns are missing (idempotent —
each add is inspector-guarded, so it is safe on a DB that was built from the
model via ``create_all`` and already has some/all of them). ``record_Identifier``
gets the same UNIQUE index the other tables received.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "refill_dismissals"
_CURRENT_TS_ON_UPDATE = sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")


def _existing(conn) -> tuple[set[str], set[str]]:
    insp = sa.inspect(conn)
    cols = {c["name"] for c in insp.get_columns(TABLE)}
    idx = {i["name"] for i in insp.get_indexes(TABLE)}
    return cols, idx


def upgrade() -> None:
    conn = op.get_bind()
    cols, idx = _existing(conn)

    if "record_Identifier" not in cols:
        op.add_column(TABLE, sa.Column("record_Identifier", sa.String(length=36), nullable=True))
    if op.f(f"ix_{TABLE}_record_Identifier") not in idx:
        op.create_index(
            op.f(f"ix_{TABLE}_record_Identifier"), TABLE, ["record_Identifier"], unique=True
        )

    if "update_record_Identifier" not in cols:
        op.add_column(
            TABLE, sa.Column("update_record_Identifier", sa.String(length=36), nullable=True)
        )
    if op.f(f"ix_{TABLE}_update_record_Identifier") not in idx:
        op.create_index(
            op.f(f"ix_{TABLE}_update_record_Identifier"),
            TABLE,
            ["update_record_Identifier"],
            unique=False,
        )

    if "IsDeleted" not in cols:
        op.add_column(
            TABLE,
            sa.Column("IsDeleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )
    if "updated_at" not in cols:
        op.add_column(
            TABLE,
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_CURRENT_TS_ON_UPDATE),
        )
    if "global_time_at" not in cols:
        op.add_column(
            TABLE,
            sa.Column("global_time_at", sa.DateTime(), nullable=False, server_default=_CURRENT_TS_ON_UPDATE),
        )
    if "delete_date_at" not in cols:
        op.add_column(TABLE, sa.Column("delete_date_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    cols, idx = _existing(conn)

    if "delete_date_at" in cols:
        op.drop_column(TABLE, "delete_date_at")
    if "global_time_at" in cols:
        op.drop_column(TABLE, "global_time_at")
    if "updated_at" in cols:
        op.drop_column(TABLE, "updated_at")
    if "IsDeleted" in cols:
        op.drop_column(TABLE, "IsDeleted")
    if op.f(f"ix_{TABLE}_update_record_Identifier") in idx:
        op.drop_index(op.f(f"ix_{TABLE}_update_record_Identifier"), table_name=TABLE)
    if "update_record_Identifier" in cols:
        op.drop_column(TABLE, "update_record_Identifier")
    if op.f(f"ix_{TABLE}_record_Identifier") in idx:
        op.drop_index(op.f(f"ix_{TABLE}_record_Identifier"), table_name=TABLE)
    if "record_Identifier" in cols:
        op.drop_column(TABLE, "record_Identifier")
