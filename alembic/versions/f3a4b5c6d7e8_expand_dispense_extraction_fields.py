"""Expand persisted dispense extraction fields.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
"""

import sqlalchemy as sa

from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    report_columns = [
        sa.Column("pharmacy_name", sa.String(200), nullable=True),
        sa.Column("pharmacy_address", sa.Text(), nullable=True),
        sa.Column("pharmacy_phone", sa.String(30), nullable=True),
        sa.Column("pharmacy_fax", sa.String(30), nullable=True),
        sa.Column("grand_total_ins_paid", sa.Numeric(12, 2), nullable=True),
    ]
    medicine_columns = [
        sa.Column("lot_number", sa.String(100), nullable=True),
        sa.Column("expiration_date", sa.String(40), nullable=True),
        sa.Column("pack_size", sa.String(100), nullable=True),
        sa.Column("manufacturer", sa.String(200), nullable=True),
        sa.Column("generic_indicator", sa.String(50), nullable=True),
        sa.Column("strength", sa.String(100), nullable=True),
        sa.Column("daw_code", sa.String(30), nullable=True),
        sa.Column("drug_schedule", sa.String(30), nullable=True),
        sa.Column("total_quantity_dispensed", sa.Numeric(12, 3), nullable=True),
    ]
    dispense_columns = [
        sa.Column("reference_number", sa.String(50), nullable=True),
        sa.Column("patient_dob", sa.String(20), nullable=True),
        sa.Column("patient_gender", sa.String(30), nullable=True),
        sa.Column("patient_id", sa.String(100), nullable=True),
        sa.Column("prescriber_dea", sa.String(30), nullable=True),
        sa.Column("prescriber_npi", sa.String(30), nullable=True),
        sa.Column("date_written", sa.String(20), nullable=True),
        sa.Column("date_sold", sa.String(20), nullable=True),
        sa.Column("will_call_date", sa.String(20), nullable=True),
        sa.Column("patient_copay", sa.Numeric(12, 2), nullable=True),
        sa.Column("cash_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("total_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("is_partial", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("extraction_warnings", sa.JSON(), nullable=True),
    ]
    for column in report_columns:
        op.add_column("drug_reports", column)
    for column in medicine_columns:
        op.add_column("medicines", column)
    for column in dispense_columns:
        op.add_column("dispenses", column)


def downgrade() -> None:
    for name in (
        "extraction_warnings",
        "is_partial",
        "source_page",
        "total_price",
        "cash_price",
        "patient_copay",
        "will_call_date",
        "date_sold",
        "date_written",
        "prescriber_npi",
        "prescriber_dea",
        "patient_id",
        "patient_gender",
        "patient_dob",
        "reference_number",
    ):
        op.drop_column("dispenses", name)
    for name in (
        "total_quantity_dispensed",
        "drug_schedule",
        "daw_code",
        "strength",
        "generic_indicator",
        "manufacturer",
        "pack_size",
        "expiration_date",
        "lot_number",
    ):
        op.drop_column("medicines", name)
    for name in (
        "grand_total_ins_paid",
        "pharmacy_fax",
        "pharmacy_phone",
        "pharmacy_address",
        "pharmacy_name",
    ):
        op.drop_column("drug_reports", name)
