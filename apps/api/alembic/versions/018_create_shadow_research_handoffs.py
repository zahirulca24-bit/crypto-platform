"""create shadow research sessions/trades and candidate handoffs

Revision ID: 018_shadow_research_handoffs
Revises: 017_strategy_matching_portfolios
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "018_shadow_research_handoffs"
down_revision = "017_strategy_matching_portfolios"
branch_labels = None
depends_on = None


def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table("shadow_research_sessions",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_type", sa.String(24), nullable=False), sa.Column("blueprint_id", uuid, sa.ForeignKey("ai_strategy_blueprints.id", ondelete="CASCADE")),
        sa.Column("variant_id", uuid, sa.ForeignKey("ai_strategy_variants.id", ondelete="CASCADE")), sa.Column("research_portfolio_id", uuid, sa.ForeignKey("research_strategy_portfolios.id", ondelete="SET NULL")),
        sa.Column("session_version", sa.String(32), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("symbol_scope", jsonb, nullable=False), sa.Column("timeframe_scope", jsonb, nullable=False), sa.Column("regime_scope", jsonb, nullable=False),
        sa.Column("configuration", jsonb, nullable=False), sa.Column("configuration_hash", sa.String(64), nullable=False), sa.Column("execution_convention", sa.String(64), nullable=False),
        sa.Column("fee_bps", sa.Numeric(12,6), nullable=False), sa.Column("slippage_bps", sa.Numeric(12,6), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("stopped_at", sa.DateTime(timezone=True)), sa.Column("last_processed_candle_time", sa.DateTime(timezone=True)),
        sa.Column("observed_candle_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("signal_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("simulated_trade_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expected_metrics", jsonb, nullable=False), sa.Column("observed_metrics", jsonb, nullable=False), sa.Column("drift_metrics", jsonb, nullable=False),
        sa.Column("readiness_score", sa.Numeric(12,8), nullable=False), sa.Column("warnings", jsonb, nullable=False), sa.Column("blocking_reasons", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_version","configuration_hash",name="uq_shadow_research_session_scope"))
    op.create_index("ix_shadow_research_session_filters","shadow_research_sessions",["status","source_type","exchange","created_at","id"])
    op.create_table("shadow_research_trades",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("session_id", uuid, sa.ForeignKey("shadow_research_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("blueprint_id", uuid, sa.ForeignKey("ai_strategy_blueprints.id", ondelete="SET NULL")), sa.Column("variant_id", uuid, sa.ForeignKey("ai_strategy_variants.id", ondelete="SET NULL")),
        sa.Column("symbol",sa.String(64),nullable=False),sa.Column("timeframe",sa.String(16),nullable=False),sa.Column("side",sa.String(16),nullable=False),sa.Column("signal_time",sa.DateTime(timezone=True),nullable=False),sa.Column("entry_time",sa.DateTime(timezone=True),nullable=False),sa.Column("exit_time",sa.DateTime(timezone=True)),
        sa.Column("entry_price",sa.Numeric(30,12),nullable=False),sa.Column("exit_price",sa.Numeric(30,12)),sa.Column("quantity",sa.Numeric(30,12),nullable=False),sa.Column("gross_pnl",sa.Numeric(30,12),nullable=False),sa.Column("net_pnl",sa.Numeric(30,12),nullable=False),sa.Column("return_pct",sa.Numeric(30,12),nullable=False),sa.Column("simulated_fees",sa.Numeric(30,12),nullable=False),sa.Column("simulated_slippage",sa.Numeric(30,12),nullable=False),sa.Column("mae",sa.Numeric(30,12),nullable=False),sa.Column("mfe",sa.Numeric(30,12),nullable=False),sa.Column("holding_time_seconds",sa.Integer(),nullable=False),
        sa.Column("entry_regime",sa.String(48)),sa.Column("exit_regime",sa.String(48)),sa.Column("exit_reason",sa.String(48)),sa.Column("parameter_set_hash",sa.String(64),nullable=False),sa.Column("context",jsonb,nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint("session_id","signal_time","entry_time","parameter_set_hash",name="uq_shadow_trade_event"))
    op.create_index("ix_shadow_research_trade_session_time","shadow_research_trades",["session_id","signal_time","id"])
    op.create_table("research_candidate_handoffs",
        sa.Column("id",uuid,primary_key=True,server_default=sa.text("gen_random_uuid()")),sa.Column("source_type",sa.String(24),nullable=False),sa.Column("blueprint_id",uuid,sa.ForeignKey("ai_strategy_blueprints.id",ondelete="SET NULL")),sa.Column("variant_id",uuid,sa.ForeignKey("ai_strategy_variants.id",ondelete="SET NULL")),sa.Column("validation_id",uuid,sa.ForeignKey("blueprint_validation_runs.id",ondelete="RESTRICT"),nullable=False),sa.Column("shadow_session_id",uuid,sa.ForeignKey("shadow_research_sessions.id",ondelete="SET NULL")),sa.Column("research_portfolio_id",uuid,sa.ForeignKey("research_strategy_portfolios.id",ondelete="SET NULL")),
        sa.Column("handoff_version",sa.String(32),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("strategy_definition",jsonb,nullable=False),sa.Column("parameter_values",jsonb,nullable=False),sa.Column("symbol_scope",jsonb,nullable=False),sa.Column("timeframe_scope",jsonb,nullable=False),sa.Column("regime_scope",jsonb,nullable=False),sa.Column("validation_summary",jsonb,nullable=False),sa.Column("shadow_summary",jsonb,nullable=False),sa.Column("regime_summary",jsonb,nullable=False),sa.Column("portfolio_summary",jsonb,nullable=False),sa.Column("risk_constraints",jsonb,nullable=False),sa.Column("protection_requirements",jsonb,nullable=False),sa.Column("readiness_score",sa.Numeric(12,8),nullable=False),sa.Column("warnings",jsonb,nullable=False),sa.Column("blocking_reasons",jsonb,nullable=False),sa.Column("configuration",jsonb,nullable=False),sa.Column("configuration_hash",sa.String(64),nullable=False),sa.Column("created_candidate_id",uuid,sa.ForeignKey("research_candidate_strategies.id",ondelete="SET NULL")),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.UniqueConstraint("handoff_version","configuration_hash",name="uq_research_candidate_handoff_scope"))
    op.create_index("ix_research_candidate_handoff_filters","research_candidate_handoffs",["source_type","status","validation_id","created_at","id"])


def downgrade():
    op.drop_table("research_candidate_handoffs")
    op.drop_table("shadow_research_trades")
    op.drop_table("shadow_research_sessions")
