"""add otp_code and pharmacy_ownership_transfer tables

Backs two features that share one OTP primitive:
  * forgot-password  (OtpPurpose.PASSWORD_RESET)
  * pharmacy ownership transfer (TRANSFER_CREATE / TRANSFER_ACCEPT)

`otp_code.transfer_id` references `pharmacy_ownership_transfer`, so the
transfer table is created first.

`purpose` and `status` are plain VARCHARs rather than native ENUMs so new
values need no ALTER TYPE / table rebuild.

Idempotent (guarded by inspector checks) so a re-run after a partial apply
completes cleanly.

Revision ID: c1d2e3f4a5b6
Revises: 7790a80e32a0
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "7790a80e32a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_columns() -> list[sa.Column]:
    """The AuditMixin columns shared by every ORM table."""
    return [
        sa.Column("record_Identifier", sa.String(length=36), nullable=True),
        sa.Column("update_record_Identifier", sa.String(length=36), nullable=True),
        sa.Column("IsDeleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("delete_date_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "global_time_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
    ]


def _audit_indexes(table: str) -> None:
    op.create_index(
        op.f(f"ix_{table}_record_Identifier"), table, ["record_Identifier"], unique=True
    )
    op.create_index(
        op.f(f"ix_{table}_update_record_Identifier"),
        table,
        ["update_record_Identifier"],
        unique=False,
    )


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "pharmacy_ownership_transfer" not in tables:
        op.create_table(
            "pharmacy_ownership_transfer",
            sa.Column("transfer_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("medical_store_id", sa.Integer(), nullable=False),
            sa.Column("current_owner_id", sa.Integer(), nullable=False),
            sa.Column("new_owner_id", sa.Integer(), nullable=False),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'PENDING'"),
            ),
            sa.Column("message", sa.String(length=500), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("accepted_at", sa.DateTime(), nullable=True),
            sa.Column("rejected_at", sa.DateTime(), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(), nullable=True),
            *_audit_columns(),
            sa.ForeignKeyConstraint(
                ["medical_store_id"],
                ["medical_store.medical_store_id"],
                name="fk_transfer_medical_store_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["current_owner_id"],
                ["user.user_id"],
                name="fk_transfer_current_owner_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["new_owner_id"],
                ["user.user_id"],
                name="fk_transfer_new_owner_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
        )
        op.create_index(
            op.f("ix_pharmacy_ownership_transfer_transfer_id"),
            "pharmacy_ownership_transfer",
            ["transfer_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_pharmacy_ownership_transfer_medical_store_id"),
            "pharmacy_ownership_transfer",
            ["medical_store_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_pharmacy_ownership_transfer_current_owner_id"),
            "pharmacy_ownership_transfer",
            ["current_owner_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_pharmacy_ownership_transfer_new_owner_id"),
            "pharmacy_ownership_transfer",
            ["new_owner_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_pharmacy_ownership_transfer_status"),
            "pharmacy_ownership_transfer",
            ["status"],
            unique=False,
        )
        _audit_indexes("pharmacy_ownership_transfer")

    if "otp_code" not in tables:
        op.create_table(
            "otp_code",
            sa.Column("otp_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("purpose", sa.String(length=32), nullable=False),
            sa.Column("code_hash", sa.String(length=255), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "max_attempts", sa.Integer(), nullable=False, server_default=sa.text("5")
            ),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("medical_store_id", sa.Integer(), nullable=True),
            sa.Column("transfer_id", sa.Integer(), nullable=True),
            sa.Column("new_owner_id", sa.Integer(), nullable=True),
            *_audit_columns(),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["user.user_id"],
                name="fk_otp_user_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["medical_store_id"],
                ["medical_store.medical_store_id"],
                name="fk_otp_medical_store_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["transfer_id"],
                ["pharmacy_ownership_transfer.transfer_id"],
                name="fk_otp_transfer_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["new_owner_id"],
                ["user.user_id"],
                name="fk_otp_new_owner_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
        )
        op.create_index(op.f("ix_otp_code_otp_id"), "otp_code", ["otp_id"], unique=False)
        op.create_index(op.f("ix_otp_code_user_id"), "otp_code", ["user_id"], unique=False)
        op.create_index(op.f("ix_otp_code_purpose"), "otp_code", ["purpose"], unique=False)
        # The hot lookup in otp_service.verify_otp.
        op.create_index(
            "ix_otp_code_lookup", "otp_code", ["user_id", "purpose", "is_active"], unique=False
        )
        _audit_indexes("otp_code")


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    # otp_code first — it FKs the transfer table.
    if "otp_code" in tables:
        op.drop_table("otp_code")
    if "pharmacy_ownership_transfer" in tables:
        op.drop_table("pharmacy_ownership_transfer")
