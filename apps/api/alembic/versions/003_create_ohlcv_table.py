"""create_ohlcv_table

Revision ID: 003_create_ohlcv_table
Revises: 002_create_users_table
Create Date: 2026-09-07 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003_create_ohlcv_table'
down_revision: Union[str, None] = '002_create_users_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ohlcv_candles',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('exchange', sa.String(length=32), nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('timeframe', sa.String(length=16), nullable=False),
        sa.Column('open_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('open', sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column('high', sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column('low', sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column('close', sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column('volume', sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column('is_closed', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ohlcv_candles')),
        sa.UniqueConstraint('exchange', 'symbol', 'timeframe', 'open_time', name='uq_ohlcv_candle')
    )
    op.create_index('ix_ohlcv_query', 'ohlcv_candles', ['exchange', 'symbol', 'timeframe', 'open_time'])


def downgrade() -> None:
    op.drop_index('ix_ohlcv_query', table_name='ohlcv_candles')
    op.drop_table('ohlcv_candles')
