from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from packages.risk.engine import RiskEngine
from packages.risk.models import PortfolioSnapshot, PositionSnapshot, RiskEvaluationRequest, RiskPolicy, StrategyOrderProposal
from .models import PortfolioExposure
ZERO=Decimal('0')
class MissingEquitySnapshot(RuntimeError):pass
class PortfolioRiskService:
    def __init__(self,store,risk_engine:RiskEngine):self.store=store; self.risk_engine=risk_engine
    def exposure(self)->PortfolioExposure:
        equity=self.store.latest_equity()
        if equity is None:raise MissingEquitySnapshot('No authoritative portfolio equity snapshot is available')
        positions=self.store.open_positions(); allocations=self.store.active_allocations()
        symbol={}; strategy={}; position_exposure=ZERO
        for p in positions:
            notion=abs(p.quantity*p.current_price); position_exposure+=notion; symbol[p.symbol]=symbol.get(p.symbol,ZERO)+notion
            key=getattr(p,'strategy_key','default'); strategy[key]=strategy.get(key,ZERO)+notion
        reserved=sum((a.reserved_notional for a in allocations),ZERO)
        for a in allocations:
            symbol[a.symbol]=symbol.get(a.symbol,ZERO)+a.reserved_notional; strategy[a.strategy_key]=strategy.get(a.strategy_key,ZERO)+a.reserved_notional
        available=max(equity.cash_balance-reserved,ZERO)
        now=datetime.now(timezone.utc); day_start=now.replace(hour=0,minute=0,second=0,microsecond=0)
        daily=self.store.daily_realized_pnl(day_start)
        return PortfolioExposure(equity=equity.equity,cash_balance=equity.cash_balance,reserved_capital=reserved,available_capital=available,position_exposure=position_exposure,portfolio_exposure=position_exposure+reserved,symbol_exposure=symbol,strategy_exposure=strategy,open_positions=len(positions),daily_realized_pnl=daily,total_drawdown=max(equity.peak_equity-equity.equity,ZERO))
    def evaluate_and_reserve(self,proposal:StrategyOrderProposal,policy:RiskPolicy):
        with self.store.allocation_lock():
            exposure=self.exposure(); positions=self.store.open_positions()
            snaps=[]
            for p in positions:
                signed=p.quantity if getattr(p.side,'value',p.side)=='long' else -p.quantity
                snaps.append(PositionSnapshot(symbol=p.symbol,quantity=signed,mark_price=p.current_price,strategy_key=getattr(p,'strategy_key','default')))
            allocations=self.store.active_allocations()
            reserved_symbol={}
            reserved_strategy={}
            open_symbols={p.symbol for p in positions}
            pending_symbols=set()
            for a in allocations:
                reserved_symbol[a.symbol]=reserved_symbol.get(a.symbol,ZERO)+a.reserved_notional
                reserved_strategy[a.strategy_key]=reserved_strategy.get(a.strategy_key,ZERO)+a.reserved_notional
                if a.symbol not in open_symbols: pending_symbols.add(a.symbol)
            req=RiskEvaluationRequest(proposal=proposal,portfolio=PortfolioSnapshot(available_balance=exposure.available_capital,reserved_capital=exposure.reserved_capital,reserved_symbol_exposure=reserved_symbol,reserved_strategy_exposure=reserved_strategy,pending_position_slots=len(pending_symbols),daily_pnl=exposure.daily_realized_pnl,peak_equity=exposure.equity+exposure.total_drawdown,current_equity=exposure.equity,positions=snaps),policy=policy)
            decision=self.risk_engine.evaluate(req)
            if decision.approved:
                self.store.reserve(decision)
                self.risk_engine.store.mark_capital_reserved(decision)
            self.store.db.commit()
            observer = getattr(self.risk_engine.store, "observe", None)
            if observer is not None:
                observer(decision)
            return decision
