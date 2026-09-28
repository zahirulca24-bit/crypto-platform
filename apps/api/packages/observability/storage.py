from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from models import OperationalAlertEventModel, OperationalAlertStateModel, OperationalIncidentModel
from .logging import redact
from .models import OperationalAlert, OperationalIncident


class ObservabilityStore:
    def __init__(self, db): self.db=db

    @contextmanager
    def locked_alert_state(self, dedupe_key: str):
        row=self.db.execute(select(OperationalAlertStateModel).where(OperationalAlertStateModel.dedupe_key==dedupe_key).with_for_update()).scalar_one_or_none()
        try:
            yield row
            self.db.commit()
        except Exception:
            self.db.rollback(); raise

    def alert_state(self, dedupe_key: str):
        return self.db.execute(select(OperationalAlertStateModel).where(OperationalAlertStateModel.dedupe_key==dedupe_key)).scalar_one_or_none()

    def create_alert_state(self, alert: OperationalAlert):
        stmt=insert(OperationalAlertStateModel).values(
            dedupe_key=alert.dedupe_key,last_emitted_at=alert.emitted_at,occurrence_count=1,suppressed_count=0,
        ).on_conflict_do_nothing(index_elements=['dedupe_key'])
        result=self.db.execute(stmt); self.db.flush()
        return self.alert_state(alert.dedupe_key), result.rowcount > 0

    def append_alert(self, alert: OperationalAlert):
        self.db.add(OperationalAlertEventModel(id=alert.id,dedupe_key=alert.dedupe_key,severity=alert.severity.value,category=alert.category,alert_json=redact(alert.model_dump(mode='json')),emitted_at=alert.emitted_at)); self.db.flush(); return alert

    def alert_history(self, limit=100, offset=0):
        rows=self.db.execute(select(OperationalAlertEventModel).order_by(OperationalAlertEventModel.emitted_at.desc()).offset(offset).limit(limit)).scalars().all()
        return [OperationalAlert.model_validate(r.alert_json) for r in rows]

    def record_incident(self, incident: OperationalIncident):
        incident.context=redact(incident.context)
        values=dict(id=incident.id,incident_key=incident.incident_key,severity=incident.severity.value,status=incident.status.value,category=incident.category,incident_json=incident.model_dump(mode='json'),first_seen_at=incident.first_seen_at,last_seen_at=incident.last_seen_at)
        result=self.db.execute(insert(OperationalIncidentModel).values(**values).on_conflict_do_nothing(index_elements=['incident_key']))
        self.db.flush()
        row=self.db.execute(select(OperationalIncidentModel).where(OperationalIncidentModel.incident_key==incident.incident_key).with_for_update()).scalar_one()
        if result.rowcount > 0:
            self.db.commit(); return incident
        current=OperationalIncident.model_validate(row.incident_json)
        current.occurrence_count += 1; current.last_seen_at=incident.last_seen_at
        current.severity=incident.severity; current.title=incident.title; current.context=incident.context; current.status=incident.status
        row.severity=current.severity.value; row.status=current.status.value; row.incident_json=current.model_dump(mode='json'); row.last_seen_at=current.last_seen_at
        self.db.commit(); return current

    def incidents(self, limit=100, offset=0):
        rows=self.db.execute(select(OperationalIncidentModel).order_by(OperationalIncidentModel.last_seen_at.desc()).offset(offset).limit(limit)).scalars().all()
        return [OperationalIncident.model_validate(r.incident_json) for r in rows]
