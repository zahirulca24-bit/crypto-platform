from __future__ import annotations
import json
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select

from .models import DemoOrder, OrderStatus
from models import DemoOrderModel
from packages.research.models import ObservationCreate
from packages.research.service import observe_best_effort

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
        self._observe(order)
        return order, True

    def update(self, order: DemoOrder) -> DemoOrder:
        order.updated_at = datetime.now(timezone.utc)
        model = self.db.execute(select(DemoOrderModel).where(DemoOrderModel.id == str(order.id))).scalars().first()
        if model:
            model.order_json = order.model_dump(mode='json')
            self.db.commit()
            self._observe(order)
        return order

    def _observe(self, order: DemoOrder) -> None:
        observe_best_effort(self.db, ObservationCreate(
            event_type="order.filled" if order.status == OrderStatus.FILLED else "order.status",
            source="demo_order_store",
            exchange="demo",
            symbol=order.symbol,
            side=order.side,
            price=order.price,
            quantity=order.filled_quantity if order.filled_quantity > 0 else order.quantity,
            notional=order.price * (order.filled_quantity if order.filled_quantity > 0 else order.quantity),
            fees=order.fee,
            order_status=order.status.value,
            trade_context={
                "order_id": str(order.id),
                "risk_decision_id": str(order.risk_decision_id),
                "client_order_id": order.client_order_id,
                "exchange_order_id": order.exchange_order_id,
                "filled_quantity": str(order.filled_quantity),
            },
            error_context=order.raw_exchange_response if order.status.value == "unknown" else None,
        ))

    def list(self, limit: int = 100, offset: int = 0) -> list[DemoOrder]:
        rows = self.db.execute(select(DemoOrderModel).order_by(DemoOrderModel.created_at.desc()).offset(offset).limit(limit)).scalars().all()
        return [DemoOrder.model_validate(row.order_json) for row in rows]
