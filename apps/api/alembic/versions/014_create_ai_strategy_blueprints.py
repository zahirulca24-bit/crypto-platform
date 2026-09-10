"""create AI strategy blueprints
Revision ID: 014_ai_strategy_blueprints
Revises: 013_ai_research_runs_reviews
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="014_ai_strategy_blueprints"; down_revision="013_ai_research_runs_reviews"; branch_labels=None; depends_on=None

def upgrade():
    op.create_table("ai_strategy_blueprints",
      sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True,server_default=sa.text("gen_random_uuid()")),
      sa.Column("name",sa.String(255),nullable=False),sa.Column("description",sa.Text(),nullable=False),sa.Column("blueprint_type",sa.String(48),nullable=False),sa.Column("status",sa.String(32),nullable=False),
      sa.Column("source_ai_proposal_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("ai_research_proposals.id",ondelete="SET NULL")),sa.Column("source_review_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("ai_proposal_reviews.id",ondelete="SET NULL")),sa.Column("source_hypothesis_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("research_hypotheses.id",ondelete="SET NULL")),sa.Column("source_experiment_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("research_experiments.id",ondelete="SET NULL")),
      sa.Column("base_strategy_name",sa.String(64)),sa.Column("base_strategy_version",sa.String(32)),
      sa.Column("symbol_scope",postgresql.JSONB(),nullable=False),sa.Column("timeframe_scope",postgresql.JSONB(),nullable=False),sa.Column("regime_scope",postgresql.JSONB(),nullable=False),
      sa.Column("feature_requirements",postgresql.JSONB(),nullable=False),sa.Column("indicator_requirements",postgresql.JSONB(),nullable=False),sa.Column("entry_logic",postgresql.JSONB(),nullable=False),sa.Column("exit_logic",postgresql.JSONB(),nullable=False),sa.Column("protection_logic",postgresql.JSONB(),nullable=False),sa.Column("risk_constraints",postgresql.JSONB(),nullable=False),sa.Column("parameter_space",postgresql.JSONB(),nullable=False),sa.Column("expected_behavior",postgresql.JSONB(),nullable=False),sa.Column("invalidation_conditions",postgresql.JSONB(),nullable=False),sa.Column("evidence_summary",postgresql.JSONB(),nullable=False),sa.Column("evidence_scope",postgresql.JSONB(),nullable=False),
      sa.Column("estimated_complexity",sa.String(16),nullable=False),sa.Column("estimated_data_requirements",postgresql.JSONB(),nullable=False),sa.Column("readiness_score",sa.Numeric(8,6),nullable=False),sa.Column("warnings",postgresql.JSONB(),nullable=False),sa.Column("blocking_reasons",postgresql.JSONB(),nullable=False),
      sa.Column("provider",sa.String(64),nullable=False),sa.Column("model_name",sa.String(128),nullable=False),sa.Column("prompt_version",sa.String(32),nullable=False),sa.Column("blueprint_version",sa.String(32),nullable=False),sa.Column("configuration",postgresql.JSONB(),nullable=False),sa.Column("configuration_hash",sa.String(64),nullable=False),
      sa.Column("parent_blueprint_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("ai_strategy_blueprints.id",ondelete="SET NULL")),sa.Column("research_observation_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("research_observations.event_id",ondelete="SET NULL")),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
      sa.UniqueConstraint("blueprint_version","prompt_version","configuration_hash",name="uq_ai_strategy_blueprint_scope"))
    for c in ("source_ai_proposal_id","source_review_id","source_hypothesis_id","source_experiment_id","parent_blueprint_id","research_observation_id"): op.create_index(f"ix_ai_strategy_blueprints_{c}","ai_strategy_blueprints",[c])
    op.create_index("ix_ai_strategy_blueprint_filters","ai_strategy_blueprints",["blueprint_type","status","base_strategy_name","estimated_complexity","created_at","id"])
def downgrade(): op.drop_table("ai_strategy_blueprints")
