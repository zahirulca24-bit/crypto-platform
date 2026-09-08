"""create research experiments
Revision ID: 010_research_experiments
Revises: 009_research_hypotheses
Create Date: 2026-09-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='010_research_experiments'; down_revision='009_research_hypotheses'; branch_labels=None; depends_on=None

def upgrade():
    op.create_table('research_experiments',
        sa.Column('id',postgresql.UUID(as_uuid=True),primary_key=True,server_default=sa.text('gen_random_uuid()')),
        sa.Column('hypothesis_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('research_hypotheses.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('start_observation_event_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('research_observations.event_id',ondelete='SET NULL')),
        sa.Column('completion_observation_event_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('research_observations.event_id',ondelete='SET NULL')),
        sa.Column('experiment_type',sa.String(48),nullable=False),sa.Column('status',sa.String(16),nullable=False),
        sa.Column('symbol',sa.String(64)),sa.Column('timeframe',sa.String(16)),sa.Column('strategy_name',sa.String(64)),sa.Column('strategy_version',sa.String(32)),
        sa.Column('train_start',sa.DateTime(timezone=True),nullable=False),sa.Column('train_end',sa.DateTime(timezone=True),nullable=False),
        sa.Column('validation_start',sa.DateTime(timezone=True)),sa.Column('validation_end',sa.DateTime(timezone=True)),
        sa.Column('configuration',postgresql.JSONB(),nullable=False),sa.Column('configuration_hash',sa.String(64),nullable=False),sa.Column('experiment_version',sa.String(32),nullable=False),
        sa.Column('hypothesis_version',sa.String(32),nullable=False),sa.Column('hypothesis_configuration_hash',sa.String(64),nullable=False),
        sa.Column('sample_size',sa.Integer(),nullable=False),sa.Column('baseline_sample_size',sa.Integer(),nullable=False),
        sa.Column('result_metrics',postgresql.JSONB(),nullable=False),sa.Column('baseline_metrics',postgresql.JSONB(),nullable=False),sa.Column('comparison_metrics',postgresql.JSONB(),nullable=False),
        sa.Column('score',sa.Numeric(8,6),nullable=False),sa.Column('stability_score',sa.Numeric(8,6),nullable=False),sa.Column('data_quality_score',sa.Numeric(8,6),nullable=False),
        sa.Column('passed',sa.Boolean(),nullable=False),sa.Column('failure_reasons',postgresql.JSONB(),nullable=False),
        sa.Column('started_at',sa.DateTime(timezone=True),nullable=False),sa.Column('completed_at',sa.DateTime(timezone=True)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint('hypothesis_id','experiment_type','experiment_version','configuration_hash',name='uq_research_experiment_scope'))
    op.create_index('ix_research_experiment_hypothesis','research_experiments',['hypothesis_id'])
    op.create_index('ix_research_experiment_filters','research_experiments',['experiment_type','status','strategy_name','symbol','timeframe','passed','created_at','id'])

def downgrade(): op.drop_table('research_experiments')
