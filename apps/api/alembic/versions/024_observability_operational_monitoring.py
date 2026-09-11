"""production observability incidents and alert deduplication

Revision ID: 024_observability_operational_monitoring
Revises: 023_reconciliation_restart_recovery
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '024_observability_operational_monitoring'
down_revision = '023_reconciliation_restart_recovery'
branch_labels = None
depends_on = None


def upgrade():
    uuid=postgresql.UUID(as_uuid=True); jsonb=postgresql.JSONB(astext_type=sa.Text())
    op.create_table('operational_incidents',
        sa.Column('id',uuid,primary_key=True),sa.Column('incident_key',sa.String(160),nullable=False,unique=True),
        sa.Column('severity',sa.String(16),nullable=False),sa.Column('status',sa.String(16),nullable=False),sa.Column('category',sa.String(64),nullable=False),
        sa.Column('incident_json',jsonb,nullable=False),sa.Column('first_seen_at',sa.DateTime(timezone=True),nullable=False),sa.Column('last_seen_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_operational_incidents_status_severity','operational_incidents',['status','severity','last_seen_at'])
    op.create_table('operational_alert_state',
        sa.Column('dedupe_key',sa.String(160),primary_key=True),sa.Column('last_emitted_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('occurrence_count',sa.Integer(),nullable=False,server_default='1'),sa.Column('suppressed_count',sa.Integer(),nullable=False,server_default='0'))
    op.create_table('operational_alert_events',
        sa.Column('id',uuid,primary_key=True),sa.Column('dedupe_key',sa.String(160),nullable=False),sa.Column('severity',sa.String(16),nullable=False),
        sa.Column('category',sa.String(64),nullable=False),sa.Column('alert_json',jsonb,nullable=False),sa.Column('emitted_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_operational_alert_events_category_time','operational_alert_events',['category','emitted_at'])


def downgrade():
    op.drop_index('ix_operational_alert_events_category_time',table_name='operational_alert_events'); op.drop_table('operational_alert_events')
    op.drop_table('operational_alert_state')
    op.drop_index('ix_operational_incidents_status_severity',table_name='operational_incidents'); op.drop_table('operational_incidents')
