"""create market feature snapshots

Revision ID: 006_market_features
Revises: 005_research_observations
Create Date: 2026-09-08 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "006_market_features"
down_revision: Union[str, None] = "005_research_observations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    n = sa.Numeric(30, 12)
    op.create_table(
        "market_feature_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("candle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exchange", sa.String(32), nullable=False), sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False), sa.Column("candle_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_version", sa.String(32), nullable=False), sa.Column("configuration", jsonb, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        *[sa.Column(name, n, nullable=True) for name in [
            "return_1","log_return_1","rolling_return","rolling_volume","volatility","true_range","atr","spread","quote_volume",
            "sma_fast","sma_slow","ema_fast","ema_slow","moving_average_distance","moving_average_slope",
            "price_vs_sma_fast","price_vs_sma_slow","price_vs_ema_fast","price_vs_ema_slow","rsi","macd","macd_signal",
            "macd_histogram","momentum","candle_body_size","upper_wick","lower_wick","candle_range","range_percentile",
            "rolling_high_distance","rolling_low_distance","liquidity","spread_quality","volatility_suitability","activity","selection_score"
        ]],
        sa.Column("selection_status", sa.String(32), nullable=True), sa.Column("rejection_reasons", jsonb, nullable=True),
        sa.Column("selection_context", jsonb, nullable=True), sa.Column("extra_features", jsonb, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["candle_id"], ["ohlcv_candles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observation_event_id"], ["research_observations.event_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exchange","symbol","timeframe","candle_open_time","feature_version","configuration_hash", name="uq_market_feature_snapshot"),
    )
    op.create_index("ix_market_feature_snapshots_candle_id", "market_feature_snapshots", ["candle_id"])
    op.create_index("ix_market_feature_snapshots_observation_event_id", "market_feature_snapshots", ["observation_event_id"])
    op.create_index("ix_market_feature_lookup", "market_feature_snapshots", ["symbol","timeframe","feature_version","candle_open_time","id"])
    op.create_index("ix_market_feature_exchange_time", "market_feature_snapshots", ["exchange","candle_open_time","id"])


def downgrade() -> None:
    op.drop_index("ix_market_feature_exchange_time", table_name="market_feature_snapshots")
    op.drop_index("ix_market_feature_lookup", table_name="market_feature_snapshots")
    op.drop_index("ix_market_feature_snapshots_observation_event_id", table_name="market_feature_snapshots")
    op.drop_index("ix_market_feature_snapshots_candle_id", table_name="market_feature_snapshots")
    op.drop_table("market_feature_snapshots")
