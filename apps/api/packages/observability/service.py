from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from .logging import redact
from .models import AlertDispatchResult, AlertSeverity, OperationalAlert, OperationalIncident


class AlertService:
    """Provider-neutral durable alert emitter with dedupe/rate limiting."""
    def __init__(self, store, *, min_interval_seconds: int = 300, sink: Callable[[OperationalAlert], None] | None = None):
        self.store=store; self.min_interval=timedelta(seconds=min_interval_seconds); self.sink=sink

    def emit(self, *, dedupe_key: str, category: str, severity: AlertSeverity, message: str, context: dict | None=None) -> AlertDispatchResult:
        now=datetime.now(timezone.utc); alert=OperationalAlert(dedupe_key=dedupe_key,category=category,severity=severity,message=redact(message),context=redact(context or {}),emitted_at=now)
        emitted=False; suppressed=0
        with self.store.locked_alert_state(dedupe_key) as row:
            if row is None:
                row, created=self.store.create_alert_state(alert)
                if created:
                    self.store.append_alert(alert); emitted=True
            if not emitted:
                row.occurrence_count += 1
                if now-row.last_emitted_at < self.min_interval:
                    row.suppressed_count += 1
                    return AlertDispatchResult(emitted=False,deduplicated=True,rate_limited=True,suppressed_count=row.suppressed_count)
                row.last_emitted_at=now; suppressed=row.suppressed_count; row.suppressed_count=0
                self.store.append_alert(alert); emitted=True
        # Optional external sinks run only after durable state commits. Sink failures must
        # never roll back dedupe state or affect trading/safety execution paths.
        if emitted and self.sink:
            try: self.sink(alert)
            except Exception: pass
        return AlertDispatchResult(emitted=True,alert=alert,suppressed_count=suppressed)



class ObservabilityService:
    def __init__(self, store, alert_service: AlertService | None = None): self.store=store; self.alert_service=alert_service

    def report_incident(self, *, incident_key: str, category: str, severity: AlertSeverity | str, title: str, context: dict | None=None, alert: bool=True):
        sev=severity if isinstance(severity,AlertSeverity) else AlertSeverity(severity)
        incident=self.store.record_incident(OperationalIncident(incident_key=incident_key,category=category,severity=sev,title=title,context=redact(context or {})))
        dispatch=None
        if alert and self.alert_service and sev in {AlertSeverity.ERROR,AlertSeverity.CRITICAL}:
            dispatch=self.alert_service.emit(dedupe_key=incident_key,category=category,severity=sev,message=title,context=incident.context)
        return incident,dispatch
