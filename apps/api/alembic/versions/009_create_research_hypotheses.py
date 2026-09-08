"""create research hypotheses
Revision ID: 009_research_hypotheses
Revises: 008_trade_outcomes
Create Date: 2026-09-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='009_research_hypotheses'; down_revision='008_trade_outcomes'; branch_labels=None; depends_on=None

def upgrade():
    op.create_table('research_hypotheses',
        sa.Column('id',postgresql.UUID(as_uuid=True),primary_key=True,server_default=sa.text('gen_random_uuid()')),
        sa.Column('hypothesis_type',sa.String(32),nullable=False),sa.Column('title',sa.String(255),nullable=False),sa.Column('description',sa.Text(),nullable=False),sa.Column('status',sa.String(16),nullable=False,server_default='proposed'),
        sa.Column('strategy_name',sa.String(64)),sa.Column('strategy_version',sa.String(32)),sa.Column('symbol',sa.String(64)),sa.Column('timeframe',sa.String(16)),sa.Column('regime',sa.String(32)),
        sa.Column('feature_conditions',postgresql.JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")),sa.Column('entry_conditions',postgresql.JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")),sa.Column('exit_conditions',postgresql.JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")),sa.Column('risk_conditions',postgresql.JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")),
        sa.Column('evidence_summary',postgresql.JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")),sa.Column('source_metrics',postgresql.JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")),sa.Column('sample_size',sa.Integer(),nullable=False),sa.Column('confidence_score',sa.Numeric(8,6),nullable=False),sa.Column('priority_score',sa.Numeric(8,6),nullable=False),
        sa.Column('hypothesis_version',sa.String(32),nullable=False),sa.Column('configuration',postgresql.JSONB(),nullable=False),sa.Column('configuration_hash',sa.String(64),nullable=False),
        sa.Column('parent_hypothesis_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('research_hypotheses.id',ondelete='SET NULL')),sa.Column('observation_event_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('research_observations.event_id',ondelete='SET NULL')),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint('hypothesis_type','hypothesis_version','configuration_hash',name='uq_research_hypothesis_scope'))
    op.create_index('ix_research_hypothesis_filters','research_hypotheses',['hypothesis_type','status','strategy_name','symbol','regime','created_at','id'])

def downgrade(): op.drop_table('research_hypotheses')
