"""
alembic/versions/e2f3a4b5c6d7_rx_no_unique_key.py
──────────────────────────────────────────────────
Add medical_store_id to dispenses, backfill from parent chain,
clean up duplicate (medical_store_id, rx_no) pairs, and add
a unique composite constraint.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add medical_store_id column (nullable initially for backfill)
    op.add_column(
        "dispenses",
        sa.Column(
            "medical_store_id",
            sa.Integer(),
            sa.ForeignKey("medical_store.medical_store_id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    # 2. Backfill medical_store_id from drug_reports via medicines
    op.execute(
        """
        UPDATE dispenses d
        JOIN medicines m ON d.medicine_id = m.id
        JOIN drug_reports dr ON m.report_id = dr.id
        SET d.medical_store_id = dr.medical_store_id
        """
    )

    # 3. Soft-delete duplicate (medical_store_id, rx_no) rows — keep newest
    #    For each group of duplicates, mark all but the most recent as deleted.
    op.execute(
        """
        UPDATE dispenses d
        INNER JOIN (
            SELECT d2.id
            FROM dispenses d2
            INNER JOIN (
                SELECT medical_store_id, rx_no, MAX(created_at) AS max_created
                FROM dispenses
                WHERE rx_no IS NOT NULL
                  AND IsDeleted = 0
                GROUP BY medical_store_id, rx_no
                HAVING COUNT(*) > 1
            ) dups ON d2.medical_store_id = dups.medical_store_id
                  AND d2.rx_no = dups.rx_no
                  AND d2.created_at < dups.max_created
            WHERE d2.IsDeleted = 0
              AND d2.rx_no IS NOT NULL
        ) to_delete ON d.id = to_delete.id
        SET d.IsDeleted = 1, d.delete_date_at = NOW()
        """
    )

    # 4. Hard-delete soft-deleted rows to allow unique constraint
    op.execute(
        """
        DELETE FROM dispenses WHERE IsDeleted = 1
        """
    )

    # 5. Make medical_store_id NOT NULL now that all rows are backfilled
    op.alter_column(
        "dispenses",
        "medical_store_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # 6. Add index on medical_store_id
    op.create_index(
        "ix_dispenses_medical_store_id",
        "dispenses",
        ["medical_store_id"],
    )

    # 7. Drop old non-unique rx_no index
    op.drop_index("ix_dispenses_rx_no", table_name="dispenses")

    # 8. Create the unique composite constraint
    op.create_unique_constraint(
        "uq_dispenses_store_rx_no",
        "dispenses",
        ["medical_store_id", "rx_no"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_dispenses_store_rx_no", "dispenses", type_="unique")
    op.create_index("ix_dispenses_rx_no", "dispenses", ["rx_no"], unique=False)
    op.drop_index("ix_dispenses_medical_store_id", table_name="dispenses")
    op.drop_column("dispenses", "medical_store_id")
