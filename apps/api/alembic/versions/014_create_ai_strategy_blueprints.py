"""create governed AI strategy blueprint registry

Revision ID: 014_ai_strategy_blueprints
Revises: 011_research_candidates
Create Date: 2026-09-09

This restores the Phase-4 historical schema revision referenced by the
blueprint validation/evolution migrations.  Blueprints are research artifacts
only; they do not contain an exchange execution path or executable quantity.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "014_ai_strategy_blueprints"
down_revision = "011_research_candidates"
branch_labels = None
depends_on = None


def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "ai_strategy_blueprints",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("blueprint_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_candidate_id", uuid, sa.ForeignKey("research_candidate_strategies.id", ondelete="SET NULL")),
        sa.Column("source_hypothesis_id", uuid, sa.ForeignKey("research_hypotheses.id", ondelete="SET NULL")),
        sa.Column("source_experiment_id", uuid, sa.ForeignKey("research_experiments.id", ondelete="SET NULL")),
        sa.Column("symbol_scope", jsonb, nullable=False),
        sa.Column("timeframe_scope", jsonb, nullable=False),
        sa.Column("regime_scope", jsonb, nullable=False),
        sa.Column("feature_requirements", jsonb, nullable=False),
        sa.Column("indicator_requirements", jsonb, nullable=False),
        sa.Column("entry_logic", jsonb, nullable=False),
        sa.Column("exit_logic", jsonb, nullable=False),
        sa.Column("protection_logic", jsonb, nullable=False),
        sa.Column("risk_constraints", jsonb, nullable=False),
        sa.Column("parameter_space", jsonb, nullable=False),
        sa.Column("governance", jsonb, nullable=False),
        sa.Column("configuration", jsonb, nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", "blueprint_version", "configuration_hash", name="uq_ai_strategy_blueprint_scope"),
    )
    op.create_index("ix_ai_strategy_blueprints_source_candidate", "ai_strategy_blueprints", ["source_candidate_id"])
    op.create_index("ix_ai_strategy_blueprints_filters", "ai_strategy_blueprints", ["status", "name", "created_at", "id"])


def downgrade():
    op.drop_table("ai_strategy_blueprints")
