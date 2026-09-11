from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from models import PortfolioEquitySnapshotModel, PortfolioRiskStateModel, CapitalAllocationModel, PositionModel, DemoOrderModel, TradeOutcome
from .models import EquitySnapshot, CapitalAllocationView
from packages.positions.models import Position, PositionStatus
from packages.exchange.models import DemoOrder, OrderStatus
class PortfolioStore:
    def __init__(self,db:Session):self.db=db
    @contextmanager
    def allocation_lock(self):
        row=self.db.execute(select(PortfolioRiskStateModel).where(PortfolioRiskStateModel.id==1).with_for_update()).scalar_one_or_none()
        if row is None:
            row=PortfolioRiskStateModel(id=1,updated_at=datetime.now(timezone.utc)); self.db.add(row); self.db.flush()
            row=self.db.execute(select(PortfolioRiskStateModel).where(PortfolioRiskStateModel.id==1).with_for_update()).scalar_one()
        yield
    def latest_equity(self):
        row=self.db.execute(select(PortfolioEquitySnapshotModel).order_by(PortfolioEquitySnapshotModel.observed_at.desc()).limit(1)).scalar_one_or_none()
        if not row:return None
        return EquitySnapshot(equity=row.equity,cash_balance=row.cash_balance,peak_equity=row.peak_equity,source=row.source,observed_at=row.observed_at)
    def save_equity(self,s:EquitySnapshot):
        self.db.add(PortfolioEquitySnapshotModel(equity=s.equity,cash_balance=s.cash_balance,peak_equity=s.peak_equity,source=s.source,observed_at=s.observed_at)); self.db.commit(); return s
    def open_positions(self):
        rows=self.db.execute(select(PositionModel).where(PositionModel.status=='open')).scalars().all(); return [Position.model_validate(r.position_json) for r in rows]
    def active_allocations(self):
        rows=self.db.execute(select(CapitalAllocationModel).where(CapitalAllocationModel.status=='reserved')).scalars().all()
        result=[]
        for a in rows:
            order_row=self.db.execute(select(DemoOrderModel).where(DemoOrderModel.risk_decision_id==a.risk_decision_id)).scalar_one_or_none()
            if order_row:
                order=DemoOrder.model_validate(order_row.order_json)
                if order.status in {OrderStatus.FILLED,OrderStatus.CANCELED,OrderStatus.REJECTED}:continue
            result.append(a)
        return result
    def reserve(self,decision):
        existing=self.db.execute(select(CapitalAllocationModel).where(CapitalAllocationModel.risk_decision_id==decision.id)).scalar_one_or_none()
        if existing:return existing
        row=CapitalAllocationModel(risk_decision_id=decision.id,symbol=decision.proposal.symbol,strategy_key=decision.proposal.strategy_key,reserved_notional=decision.approved_notional,status='reserved')
        self.db.add(row); self.db.flush(); return row
    def daily_realized_pnl(self,day_start):
        rows=self.db.execute(select(TradeOutcome.net_pnl).where(TradeOutcome.exit_time>=day_start)).scalars().all(); return sum((Decimal(str(x)) for x in rows),Decimal('0'))
    def allocations(self,limit=100):
        rows=self.db.execute(select(CapitalAllocationModel).order_by(CapitalAllocationModel.created_at.desc()).limit(limit)).scalars().all()
        return [CapitalAllocationView(risk_decision_id=str(r.risk_decision_id),symbol=r.symbol,strategy_key=r.strategy_key,reserved_notional=r.reserved_notional,status=r.status) for r in rows]
