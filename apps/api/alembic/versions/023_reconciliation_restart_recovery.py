"""production reconciliation and restart recovery

Revision ID: 023_reconciliation_restart_recovery
Revises: 022_operational_safety_controls
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "023_reconciliation_restart_recovery"
down_revision = "022_operational_safety_controls"
branch_labels = None
depends_on = None


def upgrade():
    u = postgresql.UUID(as_uuid=True)
    op.create_table(
        "reconciliation_runs",
        sa.Column("id", u, primary_key=True),
        sa.Column("bot_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("run_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reconciliation_runs_bot_started", "reconciliation_runs", ["bot_id", "started_at"])
    op.create_table(
        "reconciliation_discrepancies",
        sa.Column("id", u, primary_key=True),
        sa.Column("run_id", u, sa.ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("discrepancy_json", sa.JSON(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reconciliation_discrepancies_run", "reconciliation_discrepancies", ["run_id"])
    op.create_index("ix_reconciliation_discrepancies_open_severe", "reconciliation_discrepancies", ["status", "severity", "detected_at"])
    op.create_table(
        "worker_leases",
        sa.Column("bot_id", sa.String(64), primary_key=True),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("lease_token", u, nullable=False, unique=True),
        sa.Column("lease_json", sa.JSON(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_worker_leases_expires_at", "worker_leases", ["expires_at"])


def downgrade():
    op.drop_index("ix_worker_leases_expires_at", table_name="worker_leases")
    op.drop_table("worker_leases")
    op.drop_index("ix_reconciliation_discrepancies_open_severe", table_name="reconciliation_discrepancies")
    op.drop_index("ix_reconciliation_discrepancies_run", table_name="reconciliation_discrepancies")
    op.drop_table("reconciliation_discrepancies")
    op.drop_index("ix_reconciliation_runs_bot_started", table_name="reconciliation_runs")
    op.drop_table("reconciliation_runs")
