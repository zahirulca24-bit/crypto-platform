import hashlib
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .models import BotCommand, BotCommandRequest, BotRuntimeState, JournalEvent
from models import BotRuntimeStateModel, BotCommandModel, BotJournalModel

class RuntimeStore:
    def __init__(self, db: Session):
        self.db = db

    def state(self):
        row = self.db.execute(select(BotRuntimeStateModel).where(BotRuntimeStateModel.bot_id == 'demo-bot')).scalars().first()
        if row: return BotRuntimeState.model_validate(row.state_json)
        return self.save_state(BotRuntimeState())

    def save_state(self, s):
        s.updated_at = datetime.now(timezone.utc)
        stmt = insert(BotRuntimeStateModel).values(
            bot_id=s.bot_id,
            state_json=s.model_dump(mode='json')
        ).on_conflict_do_update(
            index_elements=['bot_id'],
            set_={'state_json': s.model_dump(mode='json')}
        )
        self.db.execute(stmt)
        self.db.commit()
        return s

    def enqueue(self, r: BotCommandRequest):
        key = r.idempotency_key or hashlib.sha256(r.intent.value.encode()).hexdigest()
        cmd = BotCommand(intent=r.intent, idempotency_key=key)
        
        existing = self.db.execute(select(BotCommandModel).where(BotCommandModel.idempotency_key == key)).scalars().first()
        if existing:
            return BotCommand.model_validate(existing.command_json)
            
        model = BotCommandModel(
            id=cmd.id,
            idempotency_key=key,
            command_json=cmd.model_dump(mode='json')
        )
        self.db.add(model)
        self.db.commit()
        return cmd

    def pending(self):
        rows = self.db.execute(select(BotCommandModel)).scalars().all()
        cmds = [BotCommand.model_validate(row.command_json) for row in rows]
        return [x for x in cmds if not x.processed_at]

    def complete(self, x):
        x.processed_at = datetime.now(timezone.utc)
        model = self.db.execute(select(BotCommandModel).where(BotCommandModel.id == x.id)).scalars().first()
        if model:
            model.command_json = x.model_dump(mode='json')
            self.db.commit()

    def journal(self, t, p=None):
        e = JournalEvent(event_type=t, payload=p or {})
        model = BotJournalModel(
            id=e.id,
            event_json=e.model_dump(mode='json'),
            created_at=e.created_at
        )
        self.db.add(model)
        self.db.commit()
        return e

    def events(self, limit=100, offset=0):
        rows = self.db.execute(select(BotJournalModel).order_by(BotJournalModel.created_at.desc()).offset(offset).limit(limit)).scalars().all()
        return [JournalEvent.model_validate(row.event_json) for row in rows]
