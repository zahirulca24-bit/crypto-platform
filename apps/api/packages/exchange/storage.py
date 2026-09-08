from __future__ import annotations
import json
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select

from .models import DemoOrder, OrderStatus
from models import DemoOrderModel

class DemoOrderStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, order_id: UUID | str) -> DemoOrder | None:
        row = self.db.execute(select(DemoOrderModel).where(DemoOrderModel.id == str(order_id))).scalars().first()
        if row: return DemoOrder.model_validate(row.order_json)
        return None

    def get_by_risk_decision(self, risk_decision_id: UUID | str) -> DemoOrder | None:
        row = self.db.execute(select(DemoOrderModel).where(DemoOrderModel.risk_decision_id == str(risk_decision_id))).scalars().first()
        if row: return DemoOrder.model_validate(row.order_json)
        return None

    def create(self, order: DemoOrder) -> tuple[DemoOrder, bool]:
        existing = self.get_by_risk_decision(order.risk_decision_id)
        if existing: return existing, False
        model = DemoOrderModel(
            id=order.id,
            risk_decision_id=order.risk_decision_id,
            order_json=order.model_dump(mode='json'),
            created_at=order.created_at
        )
        self.db.add(model)
        self.db.commit()
        return order, True

    def update(self, order: DemoOrder) -> DemoOrder:
        order.updated_at = datetime.now(timezone.utc)
        model = self.db.execute(select(DemoOrderModel).where(DemoOrderModel.id == str(order.id))).scalars().first()
        if model:
            model.order_json = order.model_dump(mode='json')
            self.db.commit()
        return order

    def list(self, limit: int = 100, offset: int = 0) -> list[DemoOrder]:
        rows = self.db.execute(select(DemoOrderModel).order_by(DemoOrderModel.created_at.desc()).offset(offset).limit(limit)).scalars().all()
        return [DemoOrder.model_validate(row.order_json) for row in rows]
