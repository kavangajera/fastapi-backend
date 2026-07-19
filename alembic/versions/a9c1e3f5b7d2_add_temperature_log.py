"""add temperature_log table

Basic storage for temperature readings pushed by external temperature devices.
One row per reading; standard AuditMixin record-metadata columns included.
Not yet scoped to a pharmacy — this is a connectivity surface.

Idempotent (guarded by an inspector check) so a re-run after a partial apply
completes cleanly.

Revision ID: a9c1e3f5b7d2
Revises: f7a8b9c0d1e2
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9c1e3f5b7d2"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_columns() -> list[sa.Column]:
    """The AuditMixin columns shared by every ORM table."""
    return [
        sa.Column("record_Identifier", sa.String(length=36), nullable=True),
        sa.Column("update_record_Identifier", sa.String(length=36), nullable=True),
        sa.Column("IsDeleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("delete_date_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "global_time_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
    ]


def _audit_indexes(table: str) -> None:
    op.create_index(op.f(f"ix_{table}_record_Identifier"), table, ["record_Identifier"], unique=True)
    op.create_index(
        op.f(f"ix_{table}_update_record_Identifier"), table, ["update_record_Identifier"], unique=False
    )


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "temperature_log" not in tables:
        op.create_table(
            "temperature_log",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("temp_device_id", sa.String(length=64), nullable=False),
            sa.Column("temperature", sa.Numeric(precision=6, scale=2), nullable=False),
            sa.Column("recorded_at", sa.DateTime(), nullable=True),
            sa.Column("probe", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=True),
            *_audit_columns(),
        )
        op.create_index(op.f("ix_temperature_log_id"), "temperature_log", ["id"], unique=False)
        op.create_index(
            op.f("ix_temperature_log_temp_device_id"), "temperature_log", ["temp_device_id"], unique=False
        )
        _audit_indexes("temperature_log")


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "temperature_log" in tables:
        op.drop_table("temperature_log")
