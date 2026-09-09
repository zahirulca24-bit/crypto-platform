"""canonical Phase-2 authoritative persistence schema

Revision ID: 004_phase2_authoritative
Revises: 004_sym_selection
Create Date: 2026-09-09

This revision repairs the historical fresh-database chain by creating the real
Phase-2 persistence tables before Phase-3 migrations reference them.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004_phase2_authoritative"
down_revision = "004_sym_selection"
branch_labels = None
depends_on = None


def _json():
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade():
    op.create_table(
        "strategy_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("candle_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("configuration", _json(), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("indicator_values", _json(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("proposal", _json(), nullable=True),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("exchange", "symbol", "timeframe", "candle_open_time", "strategy_name", "strategy_version", "configuration_hash", name="uq_strategy_decision"),
    )
    op.create_table(
        "risk_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("decision_json", _json(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "demo_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("risk_decision_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("order_json", _json(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("position_json", _json(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_positions_symbol_status", "positions", ["symbol", "status", "opened_at"])
    op.create_table(
        "applied_order_fills",
        sa.Column("order_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_applied_order_fills_position_id", "applied_order_fills", ["position_id"])
    op.create_table(
        "position_protections",
        sa.Column("position_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("protection_json", _json(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "bot_runtime_state",
        sa.Column("bot_id", sa.String(64), primary_key=True),
        sa.Column("state_json", _json(), nullable=False),
    )
    op.create_table(
        "bot_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("command_json", _json(), nullable=False),
    )
    op.create_table(
        "bot_journal",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_json", _json(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_bot_journal_created_at", "bot_journal", ["created_at"])


def downgrade():
    op.drop_table("bot_journal")
    op.drop_table("bot_commands")
    op.drop_table("bot_runtime_state")
    op.drop_table("position_protections")
    op.drop_table("applied_order_fills")
    op.drop_table("positions")
    op.drop_table("demo_orders")
    op.drop_table("risk_decisions")
    op.drop_table("strategy_decisions")
