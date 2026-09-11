from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text

from models import (
    BotRuntimeStateModel, DemoOrderModel, ReconciliationRunModel, RiskDecisionModel,
    SafetyEventModel, WorkerLeaseModel,
)


def _esc(value: Any) -> str:
    return str(value).replace('\\','\\\\').replace('"','\\"').replace('\n','\\n')


def _sample(name: str, value: int | float, labels: dict[str, Any] | None=None) -> str:
    label_text=''
    if labels:
        label_text='{' + ','.join(f'{k}="{_esc(v)}"' for k,v in sorted(labels.items())) + '}'
    return f'{name}{label_text} {value}'


class PrometheusMetricsCollector:
    """Read-only metrics projection over authoritative persisted state."""
    def __init__(self, db, *, redis_probe=None, api_request_count: int=0):
        self.db=db; self.redis_probe=redis_probe; self.api_request_count=api_request_count

    def _db_ok(self) -> int:
        try: self.db.execute(text('SELECT 1')); return 1
        except Exception: return 0

    def _redis_ok(self) -> int:
        if self.redis_probe is None: return 0
        try: return 1 if self.redis_probe() else 0
        except Exception: return 0

    def render(self) -> str:
        now=datetime.now(timezone.utc); lines=[
            '# HELP crypto_api_up API process health.', '# TYPE crypto_api_up gauge', _sample('crypto_api_up',1),
            '# HELP crypto_api_requests_total Requests observed by this API process.', '# TYPE crypto_api_requests_total counter', _sample('crypto_api_requests_total',self.api_request_count),
            '# HELP crypto_database_connected PostgreSQL connectivity.', '# TYPE crypto_database_connected gauge', _sample('crypto_database_connected',self._db_ok()),
            '# HELP crypto_redis_connected Redis/Valkey connectivity.', '# TYPE crypto_redis_connected gauge', _sample('crypto_redis_connected',self._redis_ok()),
        ]
        try:
            leases=self.db.execute(select(WorkerLeaseModel)).scalars().all()
            lines += ['# HELP crypto_worker_lease_alive Durable worker lease freshness.','# TYPE crypto_worker_lease_alive gauge']
            for row in leases:
                alive=1 if row.expires_at > now else 0
                age=max((now-row.heartbeat_at).total_seconds(),0)
                lines += [_sample('crypto_worker_lease_alive',alive,{'bot_id':row.bot_id,'worker_id':row.worker_id}),_sample('crypto_worker_heartbeat_age_seconds',age,{'bot_id':row.bot_id,'worker_id':row.worker_id})]
        except Exception: pass
        try:
            states=self.db.execute(select(BotRuntimeStateModel)).scalars().all()
            lines += ['# HELP crypto_bot_state Bot runtime state (one-hot by status).','# TYPE crypto_bot_state gauge']
            for row in states:
                state=row.state_json or {}; status=state.get('status','unknown')
                lines.append(_sample('crypto_bot_state',1,{'bot_id':row.bot_id,'status':status}))
        except Exception: pass
        try:
            orders=self.db.execute(select(DemoOrderModel)).scalars().all(); statuses={}
            for row in orders:
                status=(row.order_json or {}).get('status','unknown'); statuses[status]=statuses.get(status,0)+1
            lines += ['# HELP crypto_order_submissions_total Persisted governed order submissions.','# TYPE crypto_order_submissions_total counter',_sample('crypto_order_submissions_total',len(orders)),
                      '# HELP crypto_order_failures_total Persisted rejected/unknown order outcomes.','# TYPE crypto_order_failures_total counter',_sample('crypto_order_failures_total',sum(v for k,v in statuses.items() if k in {'rejected','unknown'}))]
            for status,count in sorted(statuses.items()): lines.append(_sample('crypto_orders_total',count,{'status':status}))
        except Exception: pass
        try:
            decisions=self.db.execute(select(RiskDecisionModel)).scalars().all(); rejected=sum(1 for r in decisions if not (r.decision_json or {}).get('approved',False))
            lines += ['# HELP crypto_risk_rejections_total Persisted risk rejections.','# TYPE crypto_risk_rejections_total counter',_sample('crypto_risk_rejections_total',rejected)]
        except Exception: pass
        try:
            runs=self.db.execute(select(ReconciliationRunModel)).scalars().all(); failures=sum(1 for r in runs if r.status in {'failed','blocked'})
            lines += ['# HELP crypto_reconciliation_failures_total Failed or safety-blocked reconciliation runs.','# TYPE crypto_reconciliation_failures_total counter',_sample('crypto_reconciliation_failures_total',failures)]
        except Exception: pass
        try:
            events=self.db.execute(select(SafetyEventModel).where(SafetyEventModel.event_type=='safety.circuit_opened')).scalars().all()
            by_type={}
            for row in events:
                e=row.event_json or {}; key=e.get('scope_key','unknown'); by_type[key]=by_type.get(key,0)+1
            lines += ['# HELP crypto_circuit_breaker_activations_total Durable circuit breaker activations.','# TYPE crypto_circuit_breaker_activations_total counter']
            for key,count in sorted(by_type.items()): lines.append(_sample('crypto_circuit_breaker_activations_total',count,{'breaker':key}))
        except Exception: pass
        # This table belongs to the pre-existing research monitoring subsystem. Raw SQL
        # keeps P5-06 decoupled from its missing historical ORM/migration branch.
        try:
            rows=self.db.execute(text('SELECT worker_name,last_heartbeat,jobs_failed FROM research_monitor_worker_status')).mappings().all()
            lines += ['# HELP crypto_research_monitor_up Research monitor heartbeat freshness.','# TYPE crypto_research_monitor_up gauge']
            for row in rows:
                hb=row['last_heartbeat']; age=(now-hb).total_seconds() if hb else 10**9
                lines += [_sample('crypto_research_monitor_up',1 if age <= 120 else 0,{'worker_name':row['worker_name']}),_sample('crypto_research_monitor_jobs_failed_total',row['jobs_failed'],{'worker_name':row['worker_name']})]
        except Exception:
            lines += ['# HELP crypto_research_monitor_up Research monitor status unavailable or no worker.','# TYPE crypto_research_monitor_up gauge',_sample('crypto_research_monitor_up',0)]
        return '\n'.join(lines)+'\n'
