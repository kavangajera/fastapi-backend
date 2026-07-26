"""add pending_signup table

Backs OTP-verified registration: credentials submitted to `POST /user/signup`
are staged here and a one-time code is mailed; the `user` row is created
only when that code is redeemed, then the staged row is deleted in the same
transaction.

`email` is uniquely indexed — one signup in flight per address, so a repeat
request replaces the staged credentials instead of accumulating rows (and
only the most recently mailed code is ever live).

Nothing in `user` changes: accounts created before this migration are
already verified by virtue of existing.

Idempotent (guarded by an inspector check) so a re-run after a partial
apply completes cleanly.

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-07-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
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

    if "pending_signup" not in set(insp.get_table_names()):
        op.create_table(
            "pending_signup",
            sa.Column(
                "pending_signup_id", sa.Integer(), primary_key=True, autoincrement=True
            ),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("username", sa.String(length=100), nullable=False),
            sa.Column("contact_number", sa.String(length=10), nullable=False),
            # Both Argon2id PHC strings — no plaintext is ever stored here.
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("code_hash", sa.String(length=255), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "max_attempts", sa.Integer(), nullable=False, server_default=sa.text("5")
            ),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("send_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("last_sent_at", sa.DateTime(), nullable=False),
            sa.Column("device_id", sa.String(length=16), nullable=True),
            *_audit_columns(),
        )
        op.create_index(
            op.f("ix_pending_signup_pending_signup_id"),
            "pending_signup",
            ["pending_signup_id"],
            unique=False,
        )
        # Unique: one signup in flight per address.
        op.create_index(
            op.f("ix_pending_signup_email"), "pending_signup", ["email"], unique=True
        )
        # Drives the opportunistic purge of abandoned signups.
        op.create_index(
            "ix_pending_signup_expires_at", "pending_signup", ["expires_at"], unique=False
        )
        _audit_indexes("pending_signup")


def downgrade() -> None:
    if "pending_signup" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("pending_signup")
