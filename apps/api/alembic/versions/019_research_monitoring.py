"""create adaptive research monitoring, triggers, jobs and worker status

Revision ID: 019_research_monitoring
Revises: 018_shadow_research_handoffs
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "019_research_monitoring"
down_revision = "018_shadow_research_handoffs"
branch_labels = None
depends_on = None


def upgrade():
    uuid = postgresql.UUID(as_uuid=True); jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table("research_monitoring_policies",
        sa.Column("id",uuid,primary_key=True,server_default=sa.text("gen_random_uuid()")),sa.Column("name",sa.String(128),nullable=False),sa.Column("description",sa.Text()),sa.Column("policy_version",sa.String(32),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("scope_type",sa.String(32),nullable=False),
        sa.Column("symbol_scope",jsonb,nullable=False),sa.Column("timeframe_scope",jsonb,nullable=False),sa.Column("regime_scope",jsonb,nullable=False),sa.Column("strategy_scope",jsonb,nullable=False),
        sa.Column("blueprint_id",uuid,sa.ForeignKey("ai_strategy_blueprints.id",ondelete="SET NULL")),sa.Column("variant_id",uuid,sa.ForeignKey("ai_strategy_variants.id",ondelete="SET NULL")),sa.Column("research_portfolio_id",uuid,sa.ForeignKey("research_strategy_portfolios.id",ondelete="SET NULL")),sa.Column("shadow_session_id",uuid,sa.ForeignKey("shadow_research_sessions.id",ondelete="SET NULL")),sa.Column("candidate_id",uuid,sa.ForeignKey("research_candidate_strategies.id",ondelete="SET NULL")),
        sa.Column("trigger_rules",jsonb,nullable=False),sa.Column("thresholds",jsonb,nullable=False),sa.Column("minimum_sample_size",sa.Integer(),nullable=False),sa.Column("cooldown_seconds",sa.Integer(),nullable=False),sa.Column("last_evaluated_at",sa.DateTime(timezone=True)),sa.Column("last_triggered_at",sa.DateTime(timezone=True)),sa.Column("configuration",jsonb,nullable=False),sa.Column("configuration_hash",sa.String(64),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.UniqueConstraint("policy_version","configuration_hash",name="uq_research_monitoring_policy_scope"))
    op.create_index("ix_research_monitoring_policy_filters","research_monitoring_policies",["status","scope_type","updated_at","id"])
    op.create_table("research_trigger_events",
        sa.Column("id",uuid,primary_key=True,server_default=sa.text("gen_random_uuid()")),sa.Column("policy_id",uuid,sa.ForeignKey("research_monitoring_policies.id",ondelete="CASCADE"),nullable=False),sa.Column("trigger_type",sa.String(48),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("trigger_version",sa.String(32),nullable=False),sa.Column("detected_at",sa.DateTime(timezone=True),nullable=False),sa.Column("evidence_start",sa.DateTime(timezone=True)),sa.Column("evidence_end",sa.DateTime(timezone=True)),sa.Column("symbol",sa.String(64)),sa.Column("timeframe",sa.String(16)),sa.Column("regime",sa.String(48)),sa.Column("strategy_name",sa.String(128)),sa.Column("source_entity_type",sa.String(48)),sa.Column("source_entity_id",uuid),sa.Column("baseline_metrics",jsonb,nullable=False),sa.Column("current_metrics",jsonb,nullable=False),sa.Column("difference_metrics",jsonb,nullable=False),sa.Column("severity_score",sa.Numeric(12,8),nullable=False),sa.Column("confidence_score",sa.Numeric(12,8),nullable=False),sa.Column("evidence_scope",jsonb,nullable=False),sa.Column("trigger_reasons",jsonb,nullable=False),sa.Column("warnings",jsonb,nullable=False),sa.Column("configuration",jsonb,nullable=False),sa.Column("configuration_hash",sa.String(64),nullable=False),sa.Column("research_job_id",uuid),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.UniqueConstraint("policy_id","trigger_version","configuration_hash",name="uq_research_trigger_event_scope"))
    op.create_index("ix_research_trigger_event_filters","research_trigger_events",["policy_id","trigger_type","status","detected_at","id"])
    op.create_table("adaptive_research_jobs",
        sa.Column("id",uuid,primary_key=True,server_default=sa.text("gen_random_uuid()")),sa.Column("trigger_event_id",uuid,sa.ForeignKey("research_trigger_events.id",ondelete="SET NULL")),sa.Column("policy_id",uuid,sa.ForeignKey("research_monitoring_policies.id",ondelete="SET NULL")),sa.Column("job_type",sa.String(48),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("job_version",sa.String(32),nullable=False),sa.Column("requested_scope",jsonb,nullable=False),sa.Column("evidence_scope",jsonb,nullable=False),sa.Column("target_pipeline_stage",sa.String(48),nullable=False),sa.Column("requested_actions",jsonb,nullable=False),sa.Column("configuration",jsonb,nullable=False),sa.Column("configuration_hash",sa.String(64),nullable=False),sa.Column("started_at",sa.DateTime(timezone=True)),sa.Column("completed_at",sa.DateTime(timezone=True)),sa.Column("result_summary",jsonb,nullable=False),sa.Column("created_entity_ids",jsonb,nullable=False),sa.Column("warnings",jsonb,nullable=False),sa.Column("failure_reason",sa.Text()),sa.Column("retry_count",sa.Integer(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.UniqueConstraint("job_version","configuration_hash",name="uq_adaptive_research_job_scope"))
    op.create_index("ix_adaptive_research_job_filters","adaptive_research_jobs",["status","job_type","created_at","id"])
    op.create_foreign_key("fk_trigger_research_job","research_trigger_events","adaptive_research_jobs",["research_job_id"],["id"],ondelete="SET NULL")
    op.create_table("research_monitor_worker_status",sa.Column("worker_name",sa.String(128),primary_key=True),sa.Column("last_heartbeat",sa.DateTime(timezone=True),nullable=False),sa.Column("last_cycle_started",sa.DateTime(timezone=True)),sa.Column("last_cycle_completed",sa.DateTime(timezone=True)),sa.Column("policies_evaluated",sa.Integer(),nullable=False),sa.Column("triggers_detected",sa.Integer(),nullable=False),sa.Column("jobs_processed",sa.Integer(),nullable=False),sa.Column("jobs_failed",sa.Integer(),nullable=False),sa.Column("last_error",sa.Text()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))

def downgrade():
    op.drop_table("research_monitor_worker_status")
    op.drop_constraint("fk_trigger_research_job","research_trigger_events",type_="foreignkey")
    op.drop_table("adaptive_research_jobs")
    op.drop_table("research_trigger_events")
    op.drop_table("research_monitoring_policies")
