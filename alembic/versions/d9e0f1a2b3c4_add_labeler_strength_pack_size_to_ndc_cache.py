"""Add labeler_name / strength_text / pack_size_qty / pack_size_uom to medicine_ndc_cache.

Revision ID: d9e0f1a2b3c4
Revises: c2d3e4f5a6b7
"""

import sqlalchemy as sa

from alembic import op

revision = "d9e0f1a2b3c4"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("medicine_ndc_cache", sa.Column("labeler_name", sa.String(255), nullable=True))
    op.add_column("medicine_ndc_cache", sa.Column("strength_text", sa.String(1000), nullable=True))
    op.add_column("medicine_ndc_cache", sa.Column("pack_size_qty", sa.Numeric(12, 3), nullable=True))
    op.add_column("medicine_ndc_cache", sa.Column("pack_size_uom", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("medicine_ndc_cache", "pack_size_uom")
    op.drop_column("medicine_ndc_cache", "pack_size_qty")
    op.drop_column("medicine_ndc_cache", "strength_text")
    op.drop_column("medicine_ndc_cache", "labeler_name")
