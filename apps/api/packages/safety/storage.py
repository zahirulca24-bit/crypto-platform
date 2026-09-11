from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from models import SafetyCommandModel, SafetyEventModel, SafetyStateModel
from .models import SafetyAuditEvent, SafetyState


class SafetyStore:
    def __init__(self, db):
        self.db = db

    def _ensure_row(self):
        row = self.db.execute(select(SafetyStateModel).where(SafetyStateModel.id == 1)).scalar_one_or_none()
        if row is None:
            self.db.add(SafetyStateModel(id=1, state_json=SafetyState().model_dump(mode="json"), updated_at=datetime.now(timezone.utc)))
            self.db.flush()

    @contextmanager
    def locked_state(self):
        self._ensure_row()
        row = self.db.execute(select(SafetyStateModel).where(SafetyStateModel.id == 1).with_for_update()).scalar_one()
        state = SafetyState.model_validate(row.state_json)
        try:
            yield state
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def load_state(self) -> SafetyState:
        self._ensure_row()
        row = self.db.execute(select(SafetyStateModel).where(SafetyStateModel.id == 1)).scalar_one()
        return SafetyState.model_validate(row.state_json)

    def save_state(self, state: SafetyState) -> None:
        row = self.db.execute(select(SafetyStateModel).where(SafetyStateModel.id == 1)).scalar_one()
        row.state_json = state.model_dump(mode="json")
        row.updated_at = state.updated_at
        self.db.flush()

    def get_command(self, idempotency_key: str):
        row = self.db.execute(select(SafetyCommandModel).where(SafetyCommandModel.idempotency_key == idempotency_key)).scalar_one_or_none()
        return row.command_json if row else None

    def save_command(self, idempotency_key: str, action: str, request: dict, result: dict) -> None:
        self.db.add(SafetyCommandModel(idempotency_key=idempotency_key, action=action, command_json={"request": request, "result": result}, created_at=datetime.now(timezone.utc)))
        self.db.flush()

    def append_event(self, event: SafetyAuditEvent) -> SafetyAuditEvent:
        self.db.add(SafetyEventModel(id=event.id, event_type=event.event_type, event_json=event.model_dump(mode="json"), created_at=event.created_at))
        self.db.flush()
        return event

    def history(self, limit: int = 100, offset: int = 0) -> list[SafetyAuditEvent]:
        rows = self.db.execute(select(SafetyEventModel).order_by(SafetyEventModel.created_at.desc()).offset(offset).limit(limit)).scalars().all()
        return [SafetyAuditEvent.model_validate(r.event_json) for r in rows]
