"""forward compatibility guard for canonical Phase-2 schema

Revision ID: 021_phase2_schema_compatibility
Revises: 020_demo_strategy_manifests
Create Date: 2026-09-09

Existing installations already stamped at later heads may predate the repaired
historical edge.  This non-destructive forward revision creates only genuinely
missing Phase-2 persistence tables using the same canonical definitions.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "021_phase2_schema_compatibility"
down_revision = "020_demo_strategy_manifests"
branch_labels = None
depends_on = None

TABLES = ("strategy_decisions","risk_decisions","demo_orders","positions","applied_order_fills","position_protections","bot_runtime_state","bot_commands","bot_journal")

def _json(): return postgresql.JSONB(astext_type=sa.Text())
def _exists(name): return name in set(sa.inspect(op.get_bind()).get_table_names())

def upgrade():
    if not _exists("strategy_decisions"):
        op.create_table("strategy_decisions", sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True,server_default=sa.text("gen_random_uuid()")), sa.Column("exchange",sa.String(32),nullable=False), sa.Column("symbol",sa.String(64),nullable=False), sa.Column("timeframe",sa.String(16),nullable=False), sa.Column("candle_open_time",sa.DateTime(timezone=True),nullable=False), sa.Column("strategy_name",sa.String(64),nullable=False), sa.Column("strategy_version",sa.String(32),nullable=False), sa.Column("configuration",_json(),nullable=False), sa.Column("configuration_hash",sa.String(64),nullable=False), sa.Column("indicator_values",_json(),nullable=False), sa.Column("decision",sa.String(16),nullable=False), sa.Column("proposal",_json()), sa.Column("reason",sa.String(255),nullable=False), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()), sa.UniqueConstraint("exchange","symbol","timeframe","candle_open_time","strategy_name","strategy_version","configuration_hash",name="uq_strategy_decision"))
    if not _exists("risk_decisions"):
        op.create_table("risk_decisions", sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True), sa.Column("request_fingerprint",sa.String(64),nullable=False,unique=True), sa.Column("decision_json",_json(),nullable=False), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    if not _exists("demo_orders"):
        op.create_table("demo_orders", sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True), sa.Column("risk_decision_id",postgresql.UUID(as_uuid=True),nullable=False,unique=True), sa.Column("order_json",_json(),nullable=False), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    if not _exists("positions"):
        op.create_table("positions", sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True), sa.Column("symbol",sa.String(64),nullable=False), sa.Column("status",sa.String(32),nullable=False), sa.Column("position_json",_json(),nullable=False), sa.Column("opened_at",sa.DateTime(timezone=True),nullable=False), sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
        op.create_index("ix_positions_symbol_status","positions",["symbol","status","opened_at"])
    if not _exists("applied_order_fills"):
        op.create_table("applied_order_fills", sa.Column("order_id",postgresql.UUID(as_uuid=True),primary_key=True), sa.Column("position_id",postgresql.UUID(as_uuid=True),nullable=False), sa.Column("applied_at",sa.DateTime(timezone=True),nullable=False))
        op.create_index("ix_applied_order_fills_position_id","applied_order_fills",["position_id"])
    if not _exists("position_protections"):
        op.create_table("position_protections", sa.Column("position_id",postgresql.UUID(as_uuid=True),primary_key=True), sa.Column("protection_json",_json(),nullable=False), sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    if not _exists("bot_runtime_state"):
        op.create_table("bot_runtime_state", sa.Column("bot_id",sa.String(64),primary_key=True), sa.Column("state_json",_json(),nullable=False))
    if not _exists("bot_commands"):
        op.create_table("bot_commands", sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True), sa.Column("idempotency_key",sa.String(128),nullable=False,unique=True), sa.Column("command_json",_json(),nullable=False))
    if not _exists("bot_journal"):
        op.create_table("bot_journal", sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True), sa.Column("event_json",_json(),nullable=False), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
        op.create_index("ix_bot_journal_created_at","bot_journal",["created_at"])

def downgrade():
    # Compatibility guard is intentionally non-destructive on downgrade; historical
    # ownership of these tables belongs to 004_phase2_authoritative.
    pass
