"""add roles to enum

Revision ID: b20aadc4505e
Revises: ac114094731a
Create Date: 2026-03-13 11:42:29.683162

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b20aadc4505e'
down_revision: Union[str, None] = 'ac114094731a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
     op.execute(
        "ALTER TABLE user MODIFY role ENUM('ADMIN','PHARMACY_OWNER','TECHNICIAN')"
    )


def downgrade() -> None:
     op.execute(
        "ALTER TABLE user MODIFY role ENUM('PHARMACY_OWNER')"
    )
