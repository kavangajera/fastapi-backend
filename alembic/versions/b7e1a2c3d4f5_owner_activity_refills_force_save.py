"""owner activity, refills, force-save, inventory exp

Adds:
  - activity_log         (audit trail / activity feed)
  - refill_dismissals    (refill-list opt-out)
  - drug_reports         + force_saved / error_count / validation_errors
  - medicines            + has_errors / validation_errors
  - medicine_inventory   + exp_date

Revision ID: b7e1a2c3d4f5
Revises: 41f560f3a557
Create Date: 2026-06-17 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e1a2c3d4f5'
down_revision: Union[str, None] = '41f560f3a557'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── activity_log ────────────────────────────────────────────────
    op.create_table(
        'activity_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('medical_store_id', sa.Integer(), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('actor_role', sa.String(length=20), nullable=True),
        sa.Column('actor_name', sa.String(length=100), nullable=True),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('entity_type', sa.String(length=30), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('summary', sa.String(length=500), nullable=True),
        sa.Column('customer_name', sa.String(length=200), nullable=True),
        sa.Column('wholesaler_name', sa.String(length=200), nullable=True),
        sa.Column('search_blob', sa.Text(), nullable=True),
        sa.Column('error_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('has_errors', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('meta', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['medical_store_id'], ['medical_store.medical_store_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_user_id'], ['user.user_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_activity_log_created_at'), 'activity_log', ['created_at'], unique=False)
    op.create_index(op.f('ix_activity_log_medical_store_id'), 'activity_log', ['medical_store_id'], unique=False)
    op.create_index(op.f('ix_activity_log_action'), 'activity_log', ['action'], unique=False)
    op.create_index(op.f('ix_activity_log_customer_name'), 'activity_log', ['customer_name'], unique=False)
    op.create_index(op.f('ix_activity_log_wholesaler_name'), 'activity_log', ['wholesaler_name'], unique=False)

    # ── refill_dismissals ───────────────────────────────────────────
    op.create_table(
        'refill_dismissals',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('medical_store_id', sa.Integer(), nullable=False),
        sa.Column('patient_key', sa.String(length=40), nullable=False),
        sa.Column('drug_ndc', sa.String(length=11), nullable=False, server_default=''),
        sa.Column('dismissed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['medical_store_id'], ['medical_store.medical_store_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dismissed_by_user_id'], ['user.user_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('medical_store_id', 'patient_key', 'drug_ndc', name='uq_refill_dismissal'),
    )
    op.create_index(op.f('ix_refill_dismissals_medical_store_id'), 'refill_dismissals', ['medical_store_id'], unique=False)
    op.create_index(op.f('ix_refill_dismissals_patient_key'), 'refill_dismissals', ['patient_key'], unique=False)

    # ── force-save columns ──────────────────────────────────────────
    op.add_column('drug_reports', sa.Column('force_saved', sa.Boolean(), nullable=False, server_default=sa.text('0')))
    op.add_column('drug_reports', sa.Column('error_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('drug_reports', sa.Column('validation_errors', sa.JSON(), nullable=True))

    op.add_column('medicines', sa.Column('has_errors', sa.Boolean(), nullable=False, server_default=sa.text('0')))
    op.add_column('medicines', sa.Column('validation_errors', sa.JSON(), nullable=True))

    # ── inventory expiry ────────────────────────────────────────────
    op.add_column('medicine_inventory', sa.Column('exp_date', sa.String(length=12), nullable=True))


def downgrade() -> None:
    op.drop_column('medicine_inventory', 'exp_date')

    op.drop_column('medicines', 'validation_errors')
    op.drop_column('medicines', 'has_errors')

    op.drop_column('drug_reports', 'validation_errors')
    op.drop_column('drug_reports', 'error_count')
    op.drop_column('drug_reports', 'force_saved')

    op.drop_index(op.f('ix_refill_dismissals_patient_key'), table_name='refill_dismissals')
    op.drop_index(op.f('ix_refill_dismissals_medical_store_id'), table_name='refill_dismissals')
    op.drop_table('refill_dismissals')

    op.drop_index(op.f('ix_activity_log_wholesaler_name'), table_name='activity_log')
    op.drop_index(op.f('ix_activity_log_customer_name'), table_name='activity_log')
    op.drop_index(op.f('ix_activity_log_action'), table_name='activity_log')
    op.drop_index(op.f('ix_activity_log_medical_store_id'), table_name='activity_log')
    op.drop_index(op.f('ix_activity_log_created_at'), table_name='activity_log')
    op.drop_table('activity_log')
