"""operational safety controls

Revision ID: 022_operational_safety_controls
Revises: 021_portfolio_risk_controls
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "022_operational_safety_controls"
down_revision = "021_portfolio_risk_controls"
branch_labels = None
depends_on = None


def upgrade():
    u = postgresql.UUID(as_uuid=True)
    op.create_table(
        "safety_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("INSERT INTO safety_state (id, state_json) VALUES (1, '{\"global_control\":{\"active\":false,\"mode\":\"halted\",\"reason_code\":null,\"activated_at\":null,\"activated_by\":null},\"bots\":{},\"symbols\":{},\"circuits\":{},\"updated_at\":\"1970-01-01T00:00:00+00:00\"}'::json)")
    op.create_table(
        "safety_commands",
        sa.Column("id", u, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("command_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "safety_events",
        sa.Column("id", u, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_safety_events_type_time", "safety_events", ["event_type", "created_at"])


def downgrade():
    op.drop_index("ix_safety_events_type_time", table_name="safety_events")
    op.drop_table("safety_events")
    op.drop_table("safety_commands")
    op.drop_table("safety_state")
