"""portfolio capital allocation and risk controls
Revision ID: 021_portfolio_risk_controls
Revises: 020_demo_strategy_manifests
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="021_portfolio_risk_controls"; down_revision="020_demo_strategy_manifests"; branch_labels=None; depends_on=None
def upgrade():
    u=postgresql.UUID(as_uuid=True)
    op.create_table("portfolio_equity_snapshots",
        sa.Column("id",u,primary_key=True,server_default=sa.text("gen_random_uuid()")),
        sa.Column("equity",sa.Numeric(30,12),nullable=False),sa.Column("cash_balance",sa.Numeric(30,12),nullable=False),
        sa.Column("peak_equity",sa.Numeric(30,12),nullable=False),sa.Column("source",sa.String(32),nullable=False),
        sa.Column("observed_at",sa.DateTime(timezone=True),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_index("ix_portfolio_equity_observed_at","portfolio_equity_snapshots",["observed_at"])
    op.create_table("portfolio_risk_state",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.execute("INSERT INTO portfolio_risk_state (id) VALUES (1)")
    op.create_table("capital_allocations",
        sa.Column("id",u,primary_key=True,server_default=sa.text("gen_random_uuid()")),
        sa.Column("risk_decision_id",u,sa.ForeignKey("risk_decisions.id",ondelete="RESTRICT"),nullable=False,unique=True),
        sa.Column("symbol",sa.String(64),nullable=False),sa.Column("strategy_key",sa.String(128),nullable=False),
        sa.Column("reserved_notional",sa.Numeric(30,12),nullable=False),sa.Column("status",sa.String(24),nullable=False,server_default="reserved"),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("released_at",sa.DateTime(timezone=True)))
    op.create_index("ix_capital_allocations_status_strategy","capital_allocations",["status","strategy_key","symbol"])
def downgrade():
    op.drop_table("capital_allocations"); op.drop_table("portfolio_risk_state"); op.drop_table("portfolio_equity_snapshots")
