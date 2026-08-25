"""add temperature device registry, logging sessions, and reading attribution

Backs the end-to-end temperature-logging flow:

* ``temperature_device``          — one registered logger per row (secret stored
                                    hashed; SHA-256 lookup index + Argon2 hash).
* ``temperature_device_session``  — one logging session per row; ``current_jti``
                                    is the single token the session honours.
* ``temperature_log``             — gains device / session / store links plus a
                                    ``raw_payload`` copy of the pushed object.
                                    All nullable, so pre-existing rows load.

Idempotent (guarded by inspector checks), matching the style of
``a9c1e3f5b7d2_add_temperature_log`` so a re-run after a partial apply
completes cleanly.

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
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

    # ── temperature_device ──────────────────────────────────────────
    if "temperature_device" not in tables:
        op.create_table(
            "temperature_device",
            sa.Column("temperature_device_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("medical_store_id", sa.Integer(), nullable=False),
            sa.Column("nickname", sa.String(length=120), nullable=False),
            # SHA-256 hex of the secret: deterministic, so a presented secret
            # can be looked up. The Argon2 hash below is what authenticates it.
            sa.Column("secret_lookup", sa.String(length=64), nullable=False),
            sa.Column("secret_hash", sa.String(length=255), nullable=False),
            sa.Column("secret_hint", sa.String(length=8), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("registered_by_user_id", sa.Integer(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("last_reading_at", sa.DateTime(), nullable=True),
            sa.Column("total_readings", sa.Integer(), nullable=False, server_default="0"),
            *_audit_columns(),
            sa.ForeignKeyConstraint(
                ["medical_store_id"],
                ["medical_store.medical_store_id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["registered_by_user_id"],
                ["user.user_id"],
                ondelete="SET NULL",
                onupdate="CASCADE",
            ),
        )
        op.create_index(
            op.f("ix_temperature_device_temperature_device_id"),
            "temperature_device",
            ["temperature_device_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_temperature_device_medical_store_id"),
            "temperature_device",
            ["medical_store_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_temperature_device_secret_lookup"),
            "temperature_device",
            ["secret_lookup"],
            unique=True,
        )
        _audit_indexes("temperature_device")

    # ── temperature_device_session ──────────────────────────────────
    if "temperature_device_session" not in tables:
        op.create_table(
            "temperature_device_session",
            sa.Column("session_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("temperature_device_id", sa.Integer(), nullable=False),
            sa.Column("medical_store_id", sa.Integer(), nullable=False),
            sa.Column(
                "status", sa.String(length=20), nullable=False, server_default="ACTIVE"
            ),
            # The one token this session honours. NULL once stopped — which is
            # exactly how "stop logging" invalidates the current token.
            sa.Column("current_jti", sa.String(length=36), nullable=True),
            sa.Column("token_issued_at", sa.DateTime(), nullable=True),
            sa.Column("token_expires_at", sa.DateTime(), nullable=True),
            sa.Column("tokens_issued", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "started_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("end_reason", sa.String(length=64), nullable=True),
            sa.Column("readings_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_reading_at", sa.DateTime(), nullable=True),
            *_audit_columns(),
            sa.ForeignKeyConstraint(
                ["temperature_device_id"],
                ["temperature_device.temperature_device_id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["medical_store_id"],
                ["medical_store.medical_store_id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
        )
        for col in ("session_id", "temperature_device_id", "medical_store_id", "status", "current_jti"):
            op.create_index(
                op.f(f"ix_temperature_device_session_{col}"),
                "temperature_device_session",
                [col],
                unique=False,
            )
        _audit_indexes("temperature_device_session")

    # ── temperature_log: attribution + raw payload ──────────────────
    if "temperature_log" in tables:
        existing = {c["name"] for c in insp.get_columns("temperature_log")}

        if "temperature_device_id" not in existing:
            op.add_column(
                "temperature_log", sa.Column("temperature_device_id", sa.Integer(), nullable=True)
            )
            op.create_index(
                op.f("ix_temperature_log_temperature_device_id"),
                "temperature_log",
                ["temperature_device_id"],
                unique=False,
            )
            op.create_foreign_key(
                "fk_temperature_log_device",
                "temperature_log",
                "temperature_device",
                ["temperature_device_id"],
                ["temperature_device_id"],
                ondelete="SET NULL",
                onupdate="CASCADE",
            )

        if "session_id" not in existing:
            op.add_column("temperature_log", sa.Column("session_id", sa.Integer(), nullable=True))
            op.create_index(
                op.f("ix_temperature_log_session_id"),
                "temperature_log",
                ["session_id"],
                unique=False,
            )
            op.create_foreign_key(
                "fk_temperature_log_session",
                "temperature_log",
                "temperature_device_session",
                ["session_id"],
                ["session_id"],
                ondelete="SET NULL",
                onupdate="CASCADE",
            )

        if "medical_store_id" not in existing:
            op.add_column(
                "temperature_log", sa.Column("medical_store_id", sa.Integer(), nullable=True)
            )
            op.create_index(
                op.f("ix_temperature_log_medical_store_id"),
                "temperature_log",
                ["medical_store_id"],
                unique=False,
            )
            op.create_foreign_key(
                "fk_temperature_log_store",
                "temperature_log",
                "medical_store",
                ["medical_store_id"],
                ["medical_store_id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            )

        if "raw_payload" not in existing:
            op.add_column("temperature_log", sa.Column("raw_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "temperature_log" in tables:
        existing = {c["name"] for c in insp.get_columns("temperature_log")}
        if "raw_payload" in existing:
            op.drop_column("temperature_log", "raw_payload")
        if "medical_store_id" in existing:
            op.drop_constraint("fk_temperature_log_store", "temperature_log", type_="foreignkey")
            op.drop_index(op.f("ix_temperature_log_medical_store_id"), "temperature_log")
            op.drop_column("temperature_log", "medical_store_id")
        if "session_id" in existing:
            op.drop_constraint("fk_temperature_log_session", "temperature_log", type_="foreignkey")
            op.drop_index(op.f("ix_temperature_log_session_id"), "temperature_log")
            op.drop_column("temperature_log", "session_id")
        if "temperature_device_id" in existing:
            op.drop_constraint("fk_temperature_log_device", "temperature_log", type_="foreignkey")
            op.drop_index(op.f("ix_temperature_log_temperature_device_id"), "temperature_log")
            op.drop_column("temperature_log", "temperature_device_id")

    if "temperature_device_session" in tables:
        op.drop_table("temperature_device_session")
    if "temperature_device" in tables:
        op.drop_table("temperature_device")
