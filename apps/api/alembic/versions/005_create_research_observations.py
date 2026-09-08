"""create research observations

Revision ID: 005_research_observations
Revises: 004_sym_selection
Create Date: 2026-09-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '005_research_observations'
down_revision: Union[str, None] = '004_sym_selection'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        'research_observations',
        sa.Column('event_id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('exchange', sa.String(length=32), nullable=True),
        sa.Column('symbol', sa.String(length=64), nullable=True),
        sa.Column('timeframe', sa.String(length=16), nullable=True),
        sa.Column('bot_id', sa.String(length=64), nullable=True),
        sa.Column('strategy_name', sa.String(length=64), nullable=True),
        sa.Column('strategy_version', sa.String(length=32), nullable=True),
        sa.Column('strategy_config_hash', sa.String(length=64), nullable=True),
        sa.Column('candle_open_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('price', sa.Numeric(30, 12), nullable=True),
        sa.Column('volume', sa.Numeric(30, 12), nullable=True),
        sa.Column('spread', sa.Numeric(30, 12), nullable=True),
        sa.Column('volatility', sa.Numeric(30, 12), nullable=True),
        sa.Column('indicator_values', jsonb, nullable=True),
        sa.Column('selection_score', sa.Numeric(30, 12), nullable=True),
        sa.Column('selection_status', sa.String(length=32), nullable=True),
        sa.Column('selection_reasons', jsonb, nullable=True),
        sa.Column('side', sa.String(length=16), nullable=True),
        sa.Column('entry_price', sa.Numeric(30, 12), nullable=True),
        sa.Column('exit_price', sa.Numeric(30, 12), nullable=True),
        sa.Column('quantity', sa.Numeric(30, 12), nullable=True),
        sa.Column('notional', sa.Numeric(30, 12), nullable=True),
        sa.Column('take_profit', sa.Numeric(30, 12), nullable=True),
        sa.Column('stop_loss', sa.Numeric(30, 12), nullable=True),
        sa.Column('fees', sa.Numeric(30, 12), nullable=True),
        sa.Column('slippage', sa.Numeric(30, 12), nullable=True),
        sa.Column('realized_pnl', sa.Numeric(30, 12), nullable=True),
        sa.Column('unrealized_pnl', sa.Numeric(30, 12), nullable=True),
        sa.Column('holding_time_seconds', sa.Numeric(30, 6), nullable=True),
        sa.Column('exit_reason', sa.String(length=128), nullable=True),
        sa.Column('mae', sa.Numeric(30, 12), nullable=True),
        sa.Column('mfe', sa.Numeric(30, 12), nullable=True),
        sa.Column('strategy_decision', sa.String(length=32), nullable=True),
        sa.Column('strategy_reason', sa.Text(), nullable=True),
        sa.Column('risk_approved', sa.Boolean(), nullable=True),
        sa.Column('risk_rejection_reasons', jsonb, nullable=True),
        sa.Column('order_status', sa.String(length=32), nullable=True),
        sa.Column('protection_status', sa.String(length=32), nullable=True),
        sa.Column('reconciliation_context', jsonb, nullable=True),
        sa.Column('error_context', jsonb, nullable=True),
        sa.Column('market_context', jsonb, nullable=True),
        sa.Column('trade_context', jsonb, nullable=True),
        sa.Column('decision_context', jsonb, nullable=True),
        sa.Column('context', jsonb, nullable=True),
        sa.Column('observed_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('event_id', name=op.f('pk_research_observations')),
    )
    op.create_index('ix_research_observations_event_time', 'research_observations', ['event_type', 'observed_at', 'event_id'])
    op.create_index('ix_research_observations_symbol_time', 'research_observations', ['symbol', 'observed_at', 'event_id'])
    op.create_index('ix_research_observations_strategy_time', 'research_observations', ['strategy_name', 'observed_at', 'event_id'])


def downgrade() -> None:
    op.drop_index('ix_research_observations_strategy_time', table_name='research_observations')
    op.drop_index('ix_research_observations_symbol_time', table_name='research_observations')
    op.drop_index('ix_research_observations_event_time', table_name='research_observations')
    op.drop_table('research_observations')
