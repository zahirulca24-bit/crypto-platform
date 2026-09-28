from __future__ import annotations
import json
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .models import PositionProtection
from models import PositionProtectionModel
from packages.research.models import ObservationCreate
from packages.research.service import observe_best_effort

class ProtectionStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, position_id: UUID | str) -> PositionProtection | None:
        row = self.db.execute(select(PositionProtectionModel).where(PositionProtectionModel.position_id == (position_id if isinstance(position_id, UUID) else UUID(str(position_id))))).scalars().first()
        if row: return PositionProtection.model_validate(row.protection_json)
        return None

    def save(self, protection: PositionProtection) -> PositionProtection:
        protection.updated_at = datetime.now(timezone.utc)
        
        stmt = insert(PositionProtectionModel).values(
            position_id=protection.position_id,
            protection_json=protection.model_dump(mode='json'),
            updated_at=protection.updated_at
        ).on_conflict_do_update(
            index_elements=['position_id'],
            set_={
                'protection_json': protection.model_dump(mode='json'),
                'updated_at': protection.updated_at
            }
        )
        self.db.execute(stmt)
        self.db.commit()
        observe_best_effort(self.db, ObservationCreate(
            event_type="protection.status",
            source="protection_service",
            exchange="demo",
            take_profit=protection.tp_price,
            stop_loss=protection.sl_price,
            protection_status=protection.protection_status.value,
            reconciliation_context={
                "position_id": str(protection.position_id),
                "tp_order_id": protection.tp_order_id,
                "sl_order_id": protection.sl_order_id,
                "last_verified_at": protection.last_verified_at.isoformat() if protection.last_verified_at else None,
            },
            error_context={"reason": protection.error_reason} if protection.error_reason else None,
        ))
        return protection

    def list(self, limit: int = 100, offset: int = 0) -> list[PositionProtection]:
        rows = self.db.execute(select(PositionProtectionModel).order_by(PositionProtectionModel.updated_at.desc()).offset(offset).limit(limit)).scalars().all()
        return [PositionProtection.model_validate(row.protection_json) for row in rows]
