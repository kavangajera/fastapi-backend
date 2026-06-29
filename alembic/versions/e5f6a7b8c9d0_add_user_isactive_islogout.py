"""add IsActive / IsLogout integer flags to user

User-only state flags surfaced in every user-bearing response
(login, profile, technician creation, admin lists, impersonation):

  - IsActive  INT NOT NULL DEFAULT 1   (1 = active, 0 = deactivated)
  - IsLogout  INT NOT NULL DEFAULT 0   (1 = logged out, 0 = logged in)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("IsActive", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "user",
        sa.Column("IsLogout", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("user", "IsLogout")
    op.drop_column("user", "IsActive")
