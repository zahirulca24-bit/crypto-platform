"""create trade outcomes

Revision ID: 008_trade_outcomes
Revises: 007_market_regimes
Create Date: 2026-09-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "008_trade_outcomes"
down_revision = "007_market_regimes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trade_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_position_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("positions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("observation_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("research_observations.event_id", ondelete="SET NULL")),
        sa.Column("exchange", sa.String(32), nullable=False), sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("timeframe", sa.String(16)), sa.Column("bot_id", sa.String(64)), sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(32), nullable=False), sa.Column("strategy_config_hash", sa.String(64), nullable=False), sa.Column("side", sa.String(16), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False), sa.Column("exit_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(30,12), nullable=False), sa.Column("exit_price", sa.Numeric(30,12), nullable=False),
        sa.Column("quantity", sa.Numeric(30,12), nullable=False), sa.Column("notional", sa.Numeric(30,12), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(30,12), nullable=False), sa.Column("net_pnl", sa.Numeric(30,12), nullable=False),
        sa.Column("fees", sa.Numeric(30,12), nullable=False), sa.Column("slippage", sa.Numeric(30,12), nullable=False),
        sa.Column("holding_time_seconds", sa.Numeric(30,6), nullable=False), sa.Column("exit_reason", sa.String(32), nullable=False),
        sa.Column("tp_price", sa.Numeric(30,12)), sa.Column("sl_price", sa.Numeric(30,12)),
        sa.Column("mae", sa.Numeric(30,12), nullable=False), sa.Column("mfe", sa.Numeric(30,12), nullable=False),
        sa.Column("return_pct", sa.Numeric(30,12), nullable=False), sa.Column("risk_amount", sa.Numeric(30,12)), sa.Column("r_multiple", sa.Numeric(30,12)),
        sa.Column("regime_at_entry", sa.String(32)), sa.Column("regime_at_exit", sa.String(32)),
        sa.Column("entry_feature_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("market_feature_snapshots.id", ondelete="SET NULL")),
        sa.Column("exit_feature_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("market_feature_snapshots.id", ondelete="SET NULL")),
        sa.Column("entry_regime_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("market_regime_snapshots.id", ondelete="SET NULL")),
        sa.Column("exit_regime_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("market_regime_snapshots.id", ondelete="SET NULL")),
        sa.Column("outcome_version", sa.String(32), nullable=False), sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_position_id", "outcome_version", name="uq_trade_outcome_position_version"),
    )
    op.create_index("ix_trade_outcome_source_position_id", "trade_outcomes", ["source_position_id"])
    op.create_index("ix_trade_outcome_observation_event_id", "trade_outcomes", ["observation_event_id"])
    op.create_index("ix_trade_outcome_history", "trade_outcomes", ["symbol", "entry_time", "id"])
    op.create_index("ix_trade_outcome_strategy", "trade_outcomes", ["strategy_name", "strategy_version", "entry_time", "id"])
    op.create_index("ix_trade_outcome_regime", "trade_outcomes", ["regime_at_entry", "entry_time", "id"])


def downgrade():
    op.drop_table("trade_outcomes")
