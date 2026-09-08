"""create_symbol_selection_tables

Revision ID: 004_sym_selection
Revises: 003_create_ohlcv_table
Create Date: 2026-09-07 19:37:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '004_sym_selection'
down_revision: Union[str, None] = '003_create_ohlcv_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'symbol_selection_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('exchange', sa.String(length=32), nullable=False),
        sa.Column('configuration', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('weights', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('lookback', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('target_volatility', sa.Numeric(precision=6, scale=4), nullable=False, server_default='0.5000'),
        sa.Column('volatility_tolerance', sa.Numeric(precision=6, scale=4), nullable=False, server_default='0.5000'),
        sa.Column('winsor_percentiles', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{"low": 0.01, "high": 0.99}'),
        sa.Column('scanned_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('eligible_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('selected_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rejected_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_symbol_selection_runs')),
    )
    op.create_table(
        'symbol_selection_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('symbol', sa.String(length=64), nullable=False),
        sa.Column('selected', sa.Boolean(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('score', sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column('raw_metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('norm_metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('score_components', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('rejection_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['symbol_selection_runs.id'], name=op.f('fk_symbol_selection_results_run_id'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_symbol_selection_results')),
    )
    op.create_index('ix_symbol_selection_results_run_id', 'symbol_selection_results', ['run_id'])


def downgrade() -> None:
    op.drop_index('ix_symbol_selection_results_run_id', table_name='symbol_selection_results')
    op.drop_table('symbol_selection_results')
    op.drop_table('symbol_selection_runs')
