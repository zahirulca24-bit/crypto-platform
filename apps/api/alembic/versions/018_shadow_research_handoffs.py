"""create research portfolios, shadow sessions and governed handoffs

Revision ID: 018_shadow_research_handoffs
Revises: 016_ai_strategy_evolution
Create Date: 2026-09-09

This restores the Phase-4 historical schema revision referenced by adaptive
research monitoring and demo manifest compilation.  Handoffs remain research
governance records and never execute exchange orders directly.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "018_shadow_research_handoffs"
down_revision = "016_ai_strategy_evolution"
branch_labels = None
depends_on = None


def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "research_strategy_portfolios",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("portfolio_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("strategy_members", jsonb, nullable=False),
        sa.Column("allocation_policy", jsonb, nullable=False),
        sa.Column("risk_constraints", jsonb, nullable=False),
        sa.Column("evaluation_metrics", jsonb, nullable=False),
        sa.Column("configuration", jsonb, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", "portfolio_version", "configuration_hash", name="uq_research_strategy_portfolio_scope"),
    )
    op.create_index("ix_research_strategy_portfolios_filters", "research_strategy_portfolios", ["status", "created_at", "id"])

    op.create_table(
        "shadow_research_sessions",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("candidate_id", uuid, sa.ForeignKey("research_candidate_strategies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("blueprint_id", uuid, sa.ForeignKey("ai_strategy_blueprints.id", ondelete="SET NULL")),
        sa.Column("variant_id", uuid, sa.ForeignKey("ai_strategy_variants.id", ondelete="SET NULL")),
        sa.Column("research_portfolio_id", uuid, sa.ForeignKey("research_strategy_portfolios.id", ondelete="SET NULL")),
        sa.Column("session_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("symbol_scope", jsonb, nullable=False),
        sa.Column("timeframe_scope", jsonb, nullable=False),
        sa.Column("observed_signals", sa.Integer(), nullable=False),
        sa.Column("simulated_trades", sa.Integer(), nullable=False),
        sa.Column("performance_metrics", jsonb, nullable=False),
        sa.Column("risk_metrics", jsonb, nullable=False),
        sa.Column("execution_cost_metrics", jsonb, nullable=False),
        sa.Column("warnings", jsonb, nullable=False),
        sa.Column("configuration", jsonb, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("candidate_id", "session_version", "configuration_hash", name="uq_shadow_research_session_scope"),
    )
    op.create_index("ix_shadow_research_sessions_candidate", "shadow_research_sessions", ["candidate_id"])
    op.create_index("ix_shadow_research_sessions_filters", "shadow_research_sessions", ["status", "started_at", "id"])

    op.create_table(
        "research_candidate_handoffs",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("candidate_id", uuid, sa.ForeignKey("research_candidate_strategies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("promotion_evaluation_id", uuid, sa.ForeignKey("candidate_promotion_evaluations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("shadow_session_id", uuid, sa.ForeignKey("shadow_research_sessions.id", ondelete="SET NULL")),
        sa.Column("blueprint_id", uuid, sa.ForeignKey("ai_strategy_blueprints.id", ondelete="SET NULL")),
        sa.Column("variant_id", uuid, sa.ForeignKey("ai_strategy_variants.id", ondelete="SET NULL")),
        sa.Column("handoff_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(48), nullable=False),
        sa.Column("governance_snapshot", jsonb, nullable=False),
        sa.Column("validation_summary", jsonb, nullable=False),
        sa.Column("shadow_summary", jsonb, nullable=False),
        sa.Column("blocking_reasons", jsonb, nullable=False),
        sa.Column("warnings", jsonb, nullable=False),
        sa.Column("configuration", jsonb, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("candidate_id", "handoff_version", "configuration_hash", name="uq_research_candidate_handoff_scope"),
    )
    op.create_index("ix_research_candidate_handoffs_candidate", "research_candidate_handoffs", ["candidate_id"])
    op.create_index("ix_research_candidate_handoffs_filters", "research_candidate_handoffs", ["status", "decision", "created_at", "id"])


def downgrade():
    op.drop_table("research_candidate_handoffs")
    op.drop_table("shadow_research_sessions")
    op.drop_table("research_strategy_portfolios")
