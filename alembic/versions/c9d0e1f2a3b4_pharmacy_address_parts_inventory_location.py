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


def upgrade() -> None:
    op.add_column("medical_store", sa.Column("city", sa.String(length=120), nullable=True))
    op.add_column("medical_store", sa.Column("state", sa.String(length=120), nullable=True))
    op.add_column("medical_store", sa.Column("zip_code", sa.String(length=20), nullable=True))
    op.add_column("medical_store", sa.Column("store_code", sa.String(length=50), nullable=True))
    op.add_column("medicine_inventory", sa.Column("location", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("medicine_inventory", "location")
    op.drop_column("medical_store", "store_code")
    op.drop_column("medical_store", "zip_code")
    op.drop_column("medical_store", "state")
    op.drop_column("medical_store", "city")
