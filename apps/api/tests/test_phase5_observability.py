import io
import json
import logging
from contextlib import contextmanager
from pathlib import Path

from packages.observability.logging import JsonFormatter, correlation_id, redact
import packages.observability.logging as observability_logging
from packages.observability.models import AlertSeverity, OperationalIncident
from packages.observability.service import AlertService, ObservabilityService


class AlertState:
    def __init__(self, alert):
        self.dedupe_key=alert.dedupe_key; self.last_emitted_at=alert.emitted_at
        self.occurrence_count=1; self.suppressed_count=0


class MemoryStore:
    def __init__(self):
        self.states={}; self.alerts=[]; self.incident_by_key={}
    @contextmanager
    def locked_alert_state(self,key):
        yield self.states.get(key)
    def create_alert_state(self,alert):
        created=alert.dedupe_key not in self.states
        row=AlertState(alert); self.states.setdefault(alert.dedupe_key,row); return self.states[alert.dedupe_key], created
    def append_alert(self,alert): self.alerts.append(alert); return alert
    def record_incident(self,incident):
        existing=self.incident_by_key.get(incident.incident_key)
        if existing:
            existing.occurrence_count += 1; existing.last_seen_at=incident.last_seen_at
            existing.context=redact(incident.context); return existing
        incident.context=redact(incident.context); self.incident_by_key[incident.incident_key]=incident; return incident


def rendered_log(message, **extra):
    record=logging.LogRecord('test',logging.INFO,__file__,1,message,(),None)
    for key,value in extra.items(): setattr(record,key,value)
    return json.loads(JsonFormatter().format(record))


def test_recursive_redaction_covers_keys_bearer_tokens_and_urls():
    secret='super-secret-value'
    payload=redact({'api_key':secret,'nested':{'password':secret},'message':f'Bearer {secret} postgresql://user:{secret}@db/x'})
    raw=json.dumps(payload)
    assert secret not in raw
    assert payload['api_key']=='[REDACTED]' and payload['nested']['password']=='[REDACTED]'
    assert 'Bearer [REDACTED]' in payload['message'] and '[REDACTED]:[REDACTED]@db' in payload['message']


def test_json_log_contains_correlation_and_safe_order_ids_without_secret():
    token=correlation_id.set('req-123')
    try:
        payload=rendered_log('submission Bearer should-not-leak',order_id='order-safe',client_order_id='client-safe',authorization='Bearer raw-secret')
    finally:
        correlation_id.reset(token)
    raw=json.dumps(payload)
    assert payload['correlation_id']=='req-123'
    assert payload['order_id']=='order-safe' and payload['client_order_id']=='client-safe'
    assert 'raw-secret' not in raw and 'should-not-leak' not in raw


def test_exception_message_is_not_serialized():
    try: raise RuntimeError('password=must-not-leak')
    except RuntimeError:
        import sys
        record=logging.LogRecord('test',logging.ERROR,__file__,1,'safe failure',(),sys.exc_info())
    payload=json.loads(JsonFormatter().format(record))
    assert payload['exception_type']=='RuntimeError'
    assert 'must-not-leak' not in json.dumps(payload)


def test_alerts_are_deduplicated_and_rate_limited():
    store=MemoryStore(); sink=[]; alerts=AlertService(store,min_interval_seconds=300,sink=sink.append)
    first=alerts.emit(dedupe_key='recon:bot',category='reconciliation',severity=AlertSeverity.CRITICAL,message='blocked',context={'bot_id':'bot'})
    second=alerts.emit(dedupe_key='recon:bot',category='reconciliation',severity=AlertSeverity.CRITICAL,message='blocked again',context={'bot_id':'bot'})
    assert first.emitted is True and second.emitted is False
    assert second.deduplicated is True and second.rate_limited is True
    assert len(store.alerts)==1 and len(sink)==1 and store.states['recon:bot'].suppressed_count==1


def test_distinct_alert_keys_are_not_collapsed():
    store=MemoryStore(); alerts=AlertService(store,min_interval_seconds=300)
    assert alerts.emit(dedupe_key='a',category='order',severity=AlertSeverity.ERROR,message='a').emitted
    assert alerts.emit(dedupe_key='b',category='order',severity=AlertSeverity.ERROR,message='b').emitted
    assert len(store.alerts)==2


def test_incidents_are_durable_shape_and_context_is_redacted_before_alerting():
    store=MemoryStore(); alerts=AlertService(store,min_interval_seconds=300); service=ObservabilityService(store,alerts)
    incident,dispatch=service.report_incident(incident_key='order:1',category='order_execution',severity='critical',title='Unknown order state',context={'client_order_id':'safe-client','api_key':'never-log-this'})
    assert incident.context['client_order_id']=='safe-client'
    assert incident.context['api_key']=='[REDACTED]'
    assert dispatch.emitted is True and dispatch.alert.context['api_key']=='[REDACTED]'


def test_repeated_incident_increments_occurrence_but_alert_is_suppressed():
    store=MemoryStore(); service=ObservabilityService(store,AlertService(store,min_interval_seconds=300))
    one,_=service.report_incident(incident_key='circuit:x',category='circuit_breaker',severity='critical',title='Open')
    two,dispatch=service.report_incident(incident_key='circuit:x',category='circuit_breaker',severity='critical',title='Open')
    assert two.occurrence_count==2 and dispatch.emitted is False


def test_observability_package_has_no_exchange_execution_or_ccxt_dependency():
    root=Path(observability_logging.__file__).resolve().parent
    combined='\n'.join(p.read_text() for p in root.glob('*.py'))
    assert 'import ccxt' not in combined
    assert 'create_order(' not in combined and '.submit(' not in combined
