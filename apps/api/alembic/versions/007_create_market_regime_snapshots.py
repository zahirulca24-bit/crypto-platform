"""create market regime snapshots

Revision ID: 007_market_regimes
Revises: 006_market_features
Create Date: 2026-09-08 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "007_market_regimes"
down_revision: Union[str, None] = "006_market_features"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "market_regime_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("feature_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("candle_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("regime", sa.String(32), nullable=False),
        sa.Column("confidence_score", sa.Numeric(8, 6), nullable=False),
        sa.Column("regime_version", sa.String(32), nullable=False),
        sa.Column("configuration", jsonb, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("supporting_signals", jsonb, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("previous_regime", sa.String(32), nullable=True),
        sa.Column("current_regime", sa.String(32), nullable=False),
        sa.Column("changed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("transition_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["feature_snapshot_id"], ["market_feature_snapshots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observation_event_id"], ["research_observations.event_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("feature_snapshot_id", "regime_version", "configuration_hash", name="uq_market_regime_snapshot"),
    )
    op.create_index("ix_market_regime_snapshots_feature_snapshot_id", "market_regime_snapshots", ["feature_snapshot_id"])
    op.create_index("ix_market_regime_snapshots_observation_event_id", "market_regime_snapshots", ["observation_event_id"])
    op.create_index("ix_market_regime_history", "market_regime_snapshots", ["symbol", "timeframe", "candle_open_time", "id"])
    op.create_index("ix_market_regime_filter", "market_regime_snapshots", ["regime", "candle_open_time", "id"])


def downgrade() -> None:
    op.drop_index("ix_market_regime_filter", table_name="market_regime_snapshots")
    op.drop_index("ix_market_regime_history", table_name="market_regime_snapshots")
    op.drop_index("ix_market_regime_snapshots_observation_event_id", table_name="market_regime_snapshots")
    op.drop_index("ix_market_regime_snapshots_feature_snapshot_id", table_name="market_regime_snapshots")
    op.drop_table("market_regime_snapshots")
