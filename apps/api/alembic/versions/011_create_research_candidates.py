"""create research candidates and promotion evaluations
Revision ID: 011_research_candidates
Revises: 010_research_experiments
Create Date: 2026-09-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='011_research_candidates'; down_revision='010_research_experiments'; branch_labels=None; depends_on=None

def upgrade():
    op.create_table('research_candidate_strategies',
        sa.Column('id',postgresql.UUID(as_uuid=True),primary_key=True,server_default=sa.text('gen_random_uuid()')),
        sa.Column('name',sa.String(255),nullable=False),sa.Column('description',sa.Text(),nullable=False),
        sa.Column('source_hypothesis_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('research_hypotheses.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('source_experiment_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('research_experiments.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('base_strategy_name',sa.String(64)),sa.Column('base_strategy_version',sa.String(32)),sa.Column('candidate_version',sa.String(32),nullable=False),
        sa.Column('symbol_scope',postgresql.JSONB(),nullable=False),sa.Column('timeframe_scope',postgresql.JSONB(),nullable=False),sa.Column('regime_scope',postgresql.JSONB(),nullable=False),
        sa.Column('feature_conditions',postgresql.JSONB(),nullable=False),sa.Column('entry_conditions',postgresql.JSONB(),nullable=False),sa.Column('exit_conditions',postgresql.JSONB(),nullable=False),sa.Column('risk_conditions',postgresql.JSONB(),nullable=False),sa.Column('parameter_overrides',postgresql.JSONB(),nullable=False),
        sa.Column('evidence_summary',postgresql.JSONB(),nullable=False),sa.Column('evaluation_metrics',postgresql.JSONB(),nullable=False),
        sa.Column('experiment_score',sa.Numeric(8,6),nullable=False),sa.Column('stability_score',sa.Numeric(8,6),nullable=False),sa.Column('data_quality_score',sa.Numeric(8,6),nullable=False),
        sa.Column('status',sa.String(32),nullable=False),sa.Column('configuration',postgresql.JSONB(),nullable=False),sa.Column('configuration_hash',sa.String(64),nullable=False),
        sa.Column('parent_candidate_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('research_candidate_strategies.id',ondelete='SET NULL')),
        sa.Column('research_observation_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('research_observations.event_id',ondelete='SET NULL')),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint('source_experiment_id','candidate_version','configuration_hash',name='uq_research_candidate_scope'))
    op.create_index('ix_research_candidate_hypothesis','research_candidate_strategies',['source_hypothesis_id'])
    op.create_index('ix_research_candidate_experiment','research_candidate_strategies',['source_experiment_id'])
    op.create_index('ix_research_candidate_filters','research_candidate_strategies',['status','base_strategy_name','source_hypothesis_id','source_experiment_id','created_at','id'])
    op.create_table('candidate_promotion_evaluations',
        sa.Column('id',postgresql.UUID(as_uuid=True),primary_key=True,server_default=sa.text('gen_random_uuid()')),
        sa.Column('candidate_id',postgresql.UUID(as_uuid=True),sa.ForeignKey('research_candidate_strategies.id',ondelete='CASCADE'),nullable=False),sa.Column('gate_version',sa.String(32),nullable=False),
        sa.Column('overall_passed',sa.Boolean(),nullable=False),sa.Column('review_required',sa.Boolean(),nullable=False),
        sa.Column('sample_gate_passed',sa.Boolean(),nullable=False),sa.Column('expectancy_gate_passed',sa.Boolean(),nullable=False),sa.Column('profit_factor_gate_passed',sa.Boolean(),nullable=False),sa.Column('drawdown_gate_passed',sa.Boolean(),nullable=False),sa.Column('stability_gate_passed',sa.Boolean(),nullable=False),sa.Column('data_quality_gate_passed',sa.Boolean(),nullable=False),sa.Column('execution_cost_gate_passed',sa.Boolean(),nullable=False),sa.Column('regime_robustness_gate_passed',sa.Boolean(),nullable=False),
        sa.Column('gate_results',postgresql.JSONB(),nullable=False),sa.Column('failure_reasons',postgresql.JSONB(),nullable=False),sa.Column('warnings',postgresql.JSONB(),nullable=False),
        sa.Column('configuration',postgresql.JSONB(),nullable=False),sa.Column('configuration_hash',sa.String(64),nullable=False),sa.Column('evaluated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint('candidate_id','gate_version','configuration_hash',name='uq_candidate_promotion_scope'))
    op.create_index('ix_candidate_promotion_candidate','candidate_promotion_evaluations',['candidate_id'])
    op.create_index('ix_candidate_promotion_candidate_time','candidate_promotion_evaluations',['candidate_id','evaluated_at','id'])

def downgrade():
    op.drop_table('candidate_promotion_evaluations')
    op.drop_table('research_candidate_strategies')
