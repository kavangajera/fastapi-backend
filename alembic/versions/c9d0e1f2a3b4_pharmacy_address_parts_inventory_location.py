"""add pharmacy address parts + inventory location (mobile-app fields)

Mobile-app spec requires structured pharmacy address fields and an inventory
shelf location:

  - medical_store: city, state, zip_code, store_code  (all nullable)
  - medicine_inventory: location                      (nullable)

All nullable so existing rows and web callers keep working.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table: str, column: str) -> bool:
    return any(c["name"] == column for c in insp.get_columns(table))


def _add(insp, table: str, column: sa.Column) -> None:
    if not _has_column(insp, table, column.name):
        op.add_column(table, column)


def _drop(insp, table: str, column: str) -> None:
    if _has_column(insp, table, column):
        op.drop_column(table, column)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    _add(insp, "medical_store", sa.Column("city", sa.String(length=120), nullable=True))
    _add(insp, "medical_store", sa.Column("state", sa.String(length=120), nullable=True))
    _add(insp, "medical_store", sa.Column("zip_code", sa.String(length=20), nullable=True))
    _add(insp, "medical_store", sa.Column("store_code", sa.String(length=50), nullable=True))
    _add(insp, "medicine_inventory", sa.Column("location", sa.String(length=120), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    _drop(insp, "medicine_inventory", "location")
    _drop(insp, "medical_store", "store_code")
    _drop(insp, "medical_store", "zip_code")
    _drop(insp, "medical_store", "state")
    _drop(insp, "medical_store", "city")
