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

class ProtectionStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, position_id: UUID | str) -> PositionProtection | None:
        row = self.db.execute(select(PositionProtectionModel).where(PositionProtectionModel.position_id == str(position_id))).scalars().first()
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
        return protection

    def list(self, limit: int = 100, offset: int = 0) -> list[PositionProtection]:
        rows = self.db.execute(select(PositionProtectionModel).order_by(PositionProtectionModel.updated_at.desc()).offset(offset).limit(limit)).scalars().all()
        return [PositionProtection.model_validate(row.protection_json) for row in rows]
