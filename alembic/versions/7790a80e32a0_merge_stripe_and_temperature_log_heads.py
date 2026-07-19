"""merge stripe and temperature_log heads

Revision ID: 7790a80e32a0
Revises: 51b8d1ce7b01, a9c1e3f5b7d2
Create Date: 2026-07-19 17:42:06.247489

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7790a80e32a0'
down_revision: Union[str, None] = ('51b8d1ce7b01', 'a9c1e3f5b7d2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
