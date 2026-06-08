"""add process_type to documents

Revision ID: a1b2c3d4e5f6
Revises: 389e8d6fe81b
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '389e8d6fe81b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column(
            'process_type',
            sa.String(length=20),
            nullable=False,
            server_default='dispense',
        ),
    )
    op.create_index(
        op.f('ix_documents_process_type'),
        'documents',
        ['process_type'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_documents_process_type'), table_name='documents')
    op.drop_column('documents', 'process_type')
