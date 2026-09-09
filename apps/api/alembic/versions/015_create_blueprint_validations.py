"""create deterministic blueprint validation tables
Revision ID: 015_blueprint_validations
Revises: 014_ai_strategy_blueprints
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="015_blueprint_validations"; down_revision="014_ai_strategy_blueprints"; branch_labels=None; depends_on=None

def upgrade():
    op.create_table("blueprint_validation_runs",
      sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True,server_default=sa.text("gen_random_uuid()")),
      sa.Column("blueprint_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("ai_strategy_blueprints.id",ondelete="CASCADE"),nullable=False),
      sa.Column("validation_type",sa.String(48),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("validation_version",sa.String(32),nullable=False),
      sa.Column("symbol_scope",postgresql.JSONB(),nullable=False),sa.Column("timeframe_scope",postgresql.JSONB(),nullable=False),sa.Column("regime_scope",postgresql.JSONB(),nullable=False),
      sa.Column("data_start",sa.DateTime(timezone=True),nullable=False),sa.Column("data_end",sa.DateTime(timezone=True),nullable=False),sa.Column("train_start",sa.DateTime(timezone=True),nullable=False),sa.Column("train_end",sa.DateTime(timezone=True),nullable=False),sa.Column("validation_start",sa.DateTime(timezone=True)),sa.Column("validation_end",sa.DateTime(timezone=True)),
      sa.Column("configuration",postgresql.JSONB(),nullable=False),sa.Column("configuration_hash",sa.String(64),nullable=False),sa.Column("parameter_set",postgresql.JSONB(),nullable=False),sa.Column("parameter_set_hash",sa.String(64),nullable=False),sa.Column("parameter_results",postgresql.JSONB(),nullable=False),
      sa.Column("sample_size",sa.Integer(),nullable=False),sa.Column("signal_count",sa.Integer(),nullable=False),sa.Column("simulated_trade_count",sa.Integer(),nullable=False),
      sa.Column("train_metrics",postgresql.JSONB(),nullable=False),sa.Column("validation_metrics",postgresql.JSONB(),nullable=False),sa.Column("combined_metrics",postgresql.JSONB(),nullable=False),sa.Column("robustness_metrics",postgresql.JSONB(),nullable=False),sa.Column("execution_cost_metrics",postgresql.JSONB(),nullable=False),
      sa.Column("score",sa.Numeric(8,6),nullable=False),sa.Column("stability_score",sa.Numeric(8,6),nullable=False),sa.Column("data_quality_score",sa.Numeric(8,6),nullable=False),sa.Column("overfit_risk_score",sa.Numeric(8,6),nullable=False),sa.Column("passed",sa.Boolean(),nullable=False),sa.Column("failure_reasons",postgresql.JSONB(),nullable=False),sa.Column("warnings",postgresql.JSONB(),nullable=False),
      sa.Column("started_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("completed_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
      sa.UniqueConstraint("blueprint_id","validation_version","validation_type","configuration_hash",name="uq_blueprint_validation_run_scope"))
    op.create_index("ix_blueprint_validation_runs_blueprint_id","blueprint_validation_runs",["blueprint_id"])
    op.create_index("ix_blueprint_validation_filters","blueprint_validation_runs",["validation_type","status","passed","created_at","id"])
    op.create_index("ix_blueprint_validation_blueprint_time","blueprint_validation_runs",["blueprint_id","created_at","id"])
    op.create_table("blueprint_simulated_trades",
      sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True,server_default=sa.text("gen_random_uuid()")),
      sa.Column("validation_run_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("blueprint_validation_runs.id",ondelete="CASCADE"),nullable=False),sa.Column("blueprint_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("ai_strategy_blueprints.id",ondelete="CASCADE"),nullable=False),
      sa.Column("symbol",sa.String(64),nullable=False),sa.Column("timeframe",sa.String(16),nullable=False),sa.Column("side",sa.String(8),nullable=False),sa.Column("entry_time",sa.DateTime(timezone=True),nullable=False),sa.Column("exit_time",sa.DateTime(timezone=True),nullable=False),
      sa.Column("entry_price",sa.Numeric(30,12),nullable=False),sa.Column("exit_price",sa.Numeric(30,12),nullable=False),sa.Column("quantity",sa.Numeric(30,12),nullable=False),sa.Column("gross_pnl",sa.Numeric(30,12),nullable=False),sa.Column("net_pnl",sa.Numeric(30,12),nullable=False),sa.Column("return_pct",sa.Numeric(30,12),nullable=False),sa.Column("simulated_fees",sa.Numeric(30,12),nullable=False),sa.Column("simulated_slippage",sa.Numeric(30,12),nullable=False),sa.Column("mae",sa.Numeric(30,12),nullable=False),sa.Column("mfe",sa.Numeric(30,12),nullable=False),sa.Column("holding_time_seconds",sa.Integer(),nullable=False),sa.Column("exit_reason",sa.String(48),nullable=False),sa.Column("entry_regime",sa.String(48)),sa.Column("exit_regime",sa.String(48)),
      sa.Column("entry_feature_snapshot_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("market_feature_snapshots.id",ondelete="SET NULL")),sa.Column("entry_regime_snapshot_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("market_regime_snapshots.id",ondelete="SET NULL")),sa.Column("parameter_set_hash",sa.String(64),nullable=False),sa.Column("context",postgresql.JSONB(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_index("ix_blueprint_simulated_trades_validation_run_id","blueprint_simulated_trades",["validation_run_id"])
    op.create_index("ix_blueprint_simulated_trades_blueprint_id","blueprint_simulated_trades",["blueprint_id"])
    op.create_index("ix_blueprint_sim_trade_run_time","blueprint_simulated_trades",["validation_run_id","entry_time","id"])
    op.create_index("ix_blueprint_sim_trade_scope","blueprint_simulated_trades",["blueprint_id","symbol","timeframe","entry_time","id"])

def downgrade():
    op.drop_table("blueprint_simulated_trades"); op.drop_table("blueprint_validation_runs")
