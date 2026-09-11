"""production security authorization, encrypted credentials and audit events

Revision ID: 025_production_security_hardening
Revises: 024_observability_operational_monitoring
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "025_production_security_hardening"
down_revision = "024_observability_operational_monitoring"
branch_labels = None
depends_on = None


def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.add_column("users", sa.Column("role", sa.String(24), nullable=False, server_default="viewer"))
    op.create_check_constraint("ck_users_role", "users", "role IN ('viewer','researcher','trader','operator','admin')")
    op.create_table(
        "exchange_credentials",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("exchange_id", sa.String(32), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("api_key_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("api_secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("password_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("api_key_fingerprint", sa.String(32), nullable=False),
        sa.Column("validation_status", sa.String(24), nullable=False, server_default="unvalidated"),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", uuid, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", uuid, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("exchange_id", "environment", name="uq_exchange_credentials_exchange_environment"),
        sa.CheckConstraint("environment IN ('demo', 'live')", name="ck_exchange_credentials_environment"),
    )
    op.create_table(
        "security_audit_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("actor_user_id", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(96), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(160), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("context_json", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_security_audit_action_time", "security_audit_events", ["action", "created_at"])


def downgrade():
    op.drop_index("ix_security_audit_action_time", table_name="security_audit_events")
    op.drop_table("security_audit_events")
    op.drop_table("exchange_credentials")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "role")
