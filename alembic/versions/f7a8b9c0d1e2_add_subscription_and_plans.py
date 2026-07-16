"""add plans, subscriptions, subscription_events + seed plan catalog

Backs the subscription/entitlement layer:

  - ``plans``               — plan catalog; ``features`` JSON is the entitlement
                              source of truth read by services.feature_gate.
  - ``subscriptions``       — one live row per medical_store; ``current_period_end``
                              is the stored expiry (enforced lazily, no grace).
  - ``subscription_events`` — append-only audit trail of subscription changes.
  - seeds the four QueueRx plans (Essential / Automation Pro / Analytics Plus /
    Unlimited Supreme) with pricing (cents), features, and limits.

Every step is idempotent (guarded by an inspector check / existing-code lookup)
so a re-run after a partial apply completes cleanly.

Revision ID: f7a8b9c0d1e2
Revises: c9d0e1f2a3b4
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_columns() -> list[sa.Column]:
    """The AuditMixin columns shared by every ORM table."""
    return [
        sa.Column("record_Identifier", sa.String(length=36), nullable=True),
        sa.Column("update_record_Identifier", sa.String(length=36), nullable=True),
        sa.Column("IsDeleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("delete_date_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
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
    op.create_index(op.f(f"ix_{table}_record_Identifier"), table, ["record_Identifier"], unique=True)
    op.create_index(
        op.f(f"ix_{table}_update_record_Identifier"), table, ["update_record_Identifier"], unique=False
    )


# Feature flag keys per QueueRx Pricing Reference v2 (additive tiers).
_BASIC_FEATURES = [
    "temp_monitoring_alerts",
    "compliance_reports",
    "inventory_lite",
    "invoice_upload_manual",
    "expiration_lot_tracking",
    "overstock_monitoring",
    "multi_location_access",
]
_ADVANCED_FEATURES = _BASIC_FEATURES + [
    "invoice_to_inventory_auto",
    "inventory_reconciliation_auto",
    "top_quantity_drug_report",
    "insurance_ndc_analytics",
    "pack_size_billed_reconciliation",
    "custom_patient_med_reports",
    "refill_analysis_billings",
]
_ULTIMATE_FEATURES = _ADVANCED_FEATURES + [
    "ndc_claim_mismatch_checks",
    "days_supply_validation",
    "discontinued_drug_detection",
    "invoice_billed_cross_reconciliation",
    "annual_checkup_audit",
    "early_access_features",
]

# ── Seed data: (code, name, description, tier, monthly_cents, features, limits) ──
# Monthly-only pricing per the v2 sheet (no annual).
_SEED_PLANS = [
    (
        "BASIC",
        "Basic",
        "Compliance and inventory fundamentals for a single or multi-location "
        "independent pharmacy.",
        1,
        2900,      # $29/mo
        _BASIC_FEATURES,
        {"drug_reconciliation_limit": 250},
    ),
    (
        "ADVANCED",
        "Advanced",
        "Basic, plus invoice automation and drug-level billing analytics "
        "(up to 250 drugs).",
        2,
        17900,     # $179/mo
        _ADVANCED_FEATURES,
        {"drug_reconciliation_limit": 250},
    ),
    (
        "ULTIMATE",
        "Ultimate",
        "The full platform — unlimited dispensary intelligence plus every "
        "compliance safeguard.",
        3,
        34900,     # $349/mo
        _ULTIMATE_FEATURES,
        {},  # {} == unlimited
    ),
]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "plans" not in tables:
        op.create_table(
            "plans",
            sa.Column("plan_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(length=50), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("tier", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("monthly_price_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("features", sa.JSON(), nullable=False),
            sa.Column("limits", sa.JSON(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            *_audit_columns(),
        )
        op.create_index(op.f("ix_plans_plan_id"), "plans", ["plan_id"], unique=False)
        op.create_index(op.f("ix_plans_code"), "plans", ["code"], unique=True)
        _audit_indexes("plans")

    if "subscriptions" not in tables:
        op.create_table(
            "subscriptions",
            sa.Column("subscription_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "medical_store_id",
                sa.Integer(),
                sa.ForeignKey("medical_store.medical_store_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "plan_id",
                sa.Integer(),
                sa.ForeignKey("plans.plan_id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
            sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("current_period_end", sa.DateTime(), nullable=False),
            sa.Column("cancelled_at", sa.DateTime(), nullable=True),
            sa.Column("notes", sa.String(length=500), nullable=True),
            *_audit_columns(),
        )
        op.create_index(op.f("ix_subscriptions_subscription_id"), "subscriptions", ["subscription_id"], unique=False)
        op.create_index(op.f("ix_subscriptions_medical_store_id"), "subscriptions", ["medical_store_id"], unique=False)
        op.create_index(op.f("ix_subscriptions_plan_id"), "subscriptions", ["plan_id"], unique=False)
        op.create_index(op.f("ix_subscriptions_status"), "subscriptions", ["status"], unique=False)
        _audit_indexes("subscriptions")

    if "subscription_events" not in tables:
        op.create_table(
            "subscription_events",
            sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "subscription_id",
                sa.Integer(),
                sa.ForeignKey("subscriptions.subscription_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("action", sa.String(length=30), nullable=False),
            sa.Column("from_plan_id", sa.Integer(), nullable=True),
            sa.Column("to_plan_id", sa.Integer(), nullable=True),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=True),
            *_audit_columns(),
        )
        op.create_index(op.f("ix_subscription_events_event_id"), "subscription_events", ["event_id"], unique=False)
        op.create_index(
            op.f("ix_subscription_events_subscription_id"), "subscription_events", ["subscription_id"], unique=False
        )
        _audit_indexes("subscription_events")

    # ── Seed the plan catalog (idempotent on code) ──
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text("SELECT code FROM plans"))}
    plans_tbl = sa.table(
        "plans",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("tier", sa.Integer),
        sa.column("monthly_price_cents", sa.Integer),
        sa.column("features", sa.JSON),
        sa.column("limits", sa.JSON),
        sa.column("is_active", sa.Boolean),
    )
    to_insert = [
        {
            "code": code,
            "name": name,
            "description": description,
            "tier": tier,
            "monthly_price_cents": monthly,
            "features": features,
            "limits": limits,
            "is_active": True,
        }
        for (code, name, description, tier, monthly, features, limits) in _SEED_PLANS
        if code not in existing
    ]
    if to_insert:
        op.bulk_insert(plans_tbl, to_insert)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "subscription_events" in tables:
        op.drop_table("subscription_events")
    if "subscriptions" in tables:
        op.drop_table("subscriptions")
    if "plans" in tables:
        op.drop_table("plans")
