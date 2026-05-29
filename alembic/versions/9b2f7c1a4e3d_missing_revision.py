"""placeholder for missing revision

Revision ID: 9b2f7c1a4e3d
Revises: 554d5947377e
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b2f7c1a4e3d"
down_revision: Union[str, None] = "554d5947377e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
