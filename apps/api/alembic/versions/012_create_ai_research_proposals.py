"""create AI research proposals
Revision ID: 012_ai_research_proposals
Revises: 011_research_candidates
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "012_ai_research_proposals"
down_revision = "011_research_candidates"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "ai_research_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("provider", sa.String(64), nullable=False), sa.Column("model_name", sa.String(128), nullable=False), sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("proposal_type", sa.String(48), nullable=False), sa.Column("title", sa.String(255), nullable=False), sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("strategy_name", sa.String(64)), sa.Column("symbol", sa.String(64)), sa.Column("timeframe", sa.String(16)), sa.Column("regime", sa.String(32)),
        sa.Column("hypothesis_statement", sa.Text(), nullable=False), sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("feature_conditions", postgresql.JSONB(), nullable=False), sa.Column("entry_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("exit_conditions", postgresql.JSONB(), nullable=False), sa.Column("risk_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("parameter_suggestions", postgresql.JSONB(), nullable=False), sa.Column("supporting_evidence", postgresql.JSONB(), nullable=False),
        sa.Column("referenced_observation_ids", postgresql.JSONB(), nullable=False), sa.Column("referenced_outcome_ids", postgresql.JSONB(), nullable=False),
        sa.Column("referenced_hypothesis_ids", postgresql.JSONB(), nullable=False), sa.Column("referenced_experiment_ids", postgresql.JSONB(), nullable=False),
        sa.Column("data_scope", postgresql.JSONB(), nullable=False), sa.Column("model_confidence", sa.Numeric(8,6)), sa.Column("research_priority", sa.Numeric(8,6)),
        sa.Column("raw_model_metadata", postgresql.JSONB(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("proposal_version", sa.String(32), nullable=False), sa.Column("configuration", postgresql.JSONB(), nullable=False), sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("converted_hypothesis_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("research_hypotheses.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("proposal_version", "prompt_version", "provider", "model_name", "configuration_hash", name="uq_ai_research_proposal_scope"),
    )
    op.create_index("ix_ai_research_proposal_filters", "ai_research_proposals", ["provider","model_name","proposal_type","status","strategy_name","symbol","regime","created_at","id"])
    op.create_index("ix_ai_research_proposal_converted_hypothesis", "ai_research_proposals", ["converted_hypothesis_id"])

def downgrade():
    op.drop_table("ai_research_proposals")
