"""create AI research runs and proposal reviews
Revision ID: 013_ai_research_runs_reviews
Revises: 012_ai_research_proposals
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="013_ai_research_runs_reviews"; down_revision="012_ai_research_proposals"; branch_labels=None; depends_on=None

def upgrade():
    op.create_table("ai_research_runs",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True,server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_type",sa.String(48),nullable=False),sa.Column("status",sa.String(24),nullable=False),
        sa.Column("provider",sa.String(64),nullable=False),sa.Column("model_name",sa.String(128),nullable=False),sa.Column("prompt_version",sa.String(32),nullable=False),sa.Column("orchestrator_version",sa.String(32),nullable=False),
        sa.Column("symbol_scope",postgresql.JSONB(),nullable=False),sa.Column("timeframe_scope",postgresql.JSONB(),nullable=False),sa.Column("regime_scope",postgresql.JSONB(),nullable=False),sa.Column("strategy_scope",postgresql.JSONB(),nullable=False),
        sa.Column("data_start",sa.DateTime(timezone=True)),sa.Column("data_end",sa.DateTime(timezone=True)),sa.Column("context_summary",postgresql.JSONB(),nullable=False),sa.Column("evidence_scope",postgresql.JSONB(),nullable=False),
        sa.Column("proposals_requested",sa.Integer(),nullable=False),sa.Column("proposals_generated",sa.Integer(),nullable=False),sa.Column("proposals_accepted",sa.Integer(),nullable=False),sa.Column("proposals_suppressed",sa.Integer(),nullable=False),sa.Column("proposals_rejected",sa.Integer(),nullable=False),
        sa.Column("run_metrics",postgresql.JSONB(),nullable=False),sa.Column("warnings",postgresql.JSONB(),nullable=False),sa.Column("failure_reason",sa.Text()),sa.Column("configuration",postgresql.JSONB(),nullable=False),sa.Column("configuration_hash",sa.String(64),nullable=False),
        sa.Column("started_at",sa.DateTime(timezone=True),nullable=False),sa.Column("completed_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_index("ix_ai_research_run_filters","ai_research_runs",["run_type","status","provider","model_name","created_at","id"])
    op.create_table("ai_proposal_reviews",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True,server_default=sa.text("gen_random_uuid()")),sa.Column("proposal_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("ai_research_proposals.id",ondelete="CASCADE"),nullable=False),sa.Column("research_run_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("ai_research_runs.id",ondelete="CASCADE"),nullable=False),sa.Column("review_version",sa.String(32),nullable=False),
        sa.Column("evidence_score",sa.Numeric(8,6),nullable=False),sa.Column("novelty_score",sa.Numeric(8,6),nullable=False),sa.Column("testability_score",sa.Numeric(8,6),nullable=False),sa.Column("data_quality_score",sa.Numeric(8,6),nullable=False),sa.Column("safety_score",sa.Numeric(8,6),nullable=False),sa.Column("overall_score",sa.Numeric(8,6),nullable=False),
        sa.Column("accepted_for_review",sa.Boolean(),nullable=False),sa.Column("suppressed",sa.Boolean(),nullable=False),sa.Column("rejection_reasons",postgresql.JSONB(),nullable=False),sa.Column("warnings",postgresql.JSONB(),nullable=False),sa.Column("review_metrics",postgresql.JSONB(),nullable=False),sa.Column("configuration",postgresql.JSONB(),nullable=False),sa.Column("configuration_hash",sa.String(64),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint("proposal_id","research_run_id","review_version","configuration_hash",name="uq_ai_proposal_review_scope"))
    op.create_index("ix_ai_proposal_review_proposal","ai_proposal_reviews",["proposal_id"]); op.create_index("ix_ai_proposal_review_run","ai_proposal_reviews",["research_run_id"]); op.create_index("ix_ai_proposal_review_run_score","ai_proposal_reviews",["research_run_id","overall_score","id"])

def downgrade():
    op.drop_table("ai_proposal_reviews"); op.drop_table("ai_research_runs")
