"""add delete_date_at (soft-delete timestamp) to every AuditMixin table

Completes the mobile-app "Common parameter" list: ``IsDeleted`` already
existed, but nothing recorded *when* the row was soft-deleted. Adds a nullable
``delete_date_at`` (UTC) to every AuditMixin table. It is auto-stamped when
``IsDeleted`` flips true and cleared on restore by the ``before_flush`` hook in
``core/async_db.py`` — no back-fill (existing deleted rows, if any, keep NULL).

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES: list[str] = [
    "user",
    "refresh_tokens",
    "medical_store",
    "drug_reports",
    "medicines",
    "dispenses",
    "invoices",
    "invoice_line_items",
    "invoice_summaries",
    "medicine_inventory",
    "medicine_ndc_cache",
    "documents",
    "activity_log",
]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("delete_date_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_column(table, "delete_date_at")
