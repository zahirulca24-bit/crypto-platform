from __future__ import annotations
import json
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .models import Position
from models import PositionModel, AppliedOrderFillModel

class PositionStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, position_id: UUID | str) -> Position | None:
        row = self.db.execute(select(PositionModel).where(PositionModel.id == str(position_id))).scalars().first()
        if row: return Position.model_validate(row.position_json)
        return None

    def get_open_for_symbol(self, symbol: str) -> Position | None:
        row = self.db.execute(
            select(PositionModel).where(PositionModel.symbol == symbol, PositionModel.status == 'open')
            .order_by(PositionModel.opened_at.desc()).limit(1)
        ).scalars().first()
        if row: return Position.model_validate(row.position_json)
        return None

    def save(self, position: Position) -> Position:
        position.updated_at = datetime.now(timezone.utc)
        
        stmt = insert(PositionModel).values(
            id=position.id,
            symbol=position.symbol,
            status=position.status.value,
            position_json=position.model_dump(mode='json'),
            opened_at=position.opened_at,
            updated_at=position.updated_at
        ).on_conflict_do_update(
            index_elements=['id'],
            set_={
                'status': position.status.value,
                'position_json': position.model_dump(mode='json'),
                'updated_at': position.updated_at
            }
        )
        self.db.execute(stmt)
        self.db.commit()
        return position

    def claim_fill(self, order_id: UUID | str, position_id: UUID | str) -> bool:
        stmt = insert(AppliedOrderFillModel).values(
            order_id=order_id,
            position_id=position_id,
            applied_at=datetime.now(timezone.utc)
        ).on_conflict_do_nothing(index_elements=['order_id'])
        result = self.db.execute(stmt)
        self.db.commit()
        return result.rowcount > 0

    def get_position_for_fill(self, order_id: UUID | str) -> Position | None:
        row = self.db.execute(select(AppliedOrderFillModel).where(AppliedOrderFillModel.order_id == str(order_id))).scalars().first()
        if row: return self.get(row.position_id)
        return None

    def list(self, limit: int = 100, offset: int = 0) -> list[Position]:
        rows = self.db.execute(select(PositionModel).order_by(PositionModel.updated_at.desc()).offset(offset).limit(limit)).scalars().all()
        return [Position.model_validate(row.position_json) for row in rows]
