from decimal import Decimal
from threading import Lock, Thread
from contextlib import contextmanager
from types import SimpleNamespace
from packages.risk.engine import RiskEngine
from packages.risk.models import StrategyOrderProposal, RiskPolicy, RiskDecision
from packages.portfolio.service import PortfolioRiskService, MissingEquitySnapshot
from packages.portfolio.models import EquitySnapshot

class DecisionStore:
    def __init__(self): self.by_fp={}; self.by_id={}
    def get_by_fingerprint(self,fp): return self.by_fp.get(fp)
    def save(self,fp,d):
        old=self.by_fp.get(fp)
        if old:return old
        self.by_fp[fp]=d; self.by_id[str(d.id)]=d; return d
    def mark_capital_reserved(self,d): d.capital_reserved=True; return d

class DB:
    def commit(self): pass

class Store:
    def __init__(self,equity='1000',cash='1000',peak='1000'):
        self.eq=EquitySnapshot(equity=Decimal(equity),cash_balance=Decimal(cash),peak_equity=Decimal(peak))
        self.alloc=[]; self.positions=[]; self.loss=Decimal('0'); self.lock=Lock(); self.db=DB()
    @contextmanager
    def allocation_lock(self):
        with self.lock: yield
    def latest_equity(self): return self.eq
    def open_positions(self): return list(self.positions)
    def active_allocations(self): return list(self.alloc)
    def reserve(self,d):
        a=SimpleNamespace(risk_decision_id=d.id,symbol=d.proposal.symbol,strategy_key=d.proposal.strategy_key,reserved_notional=d.approved_notional,status='reserved')
        self.alloc.append(a); return a
    def daily_realized_pnl(self,start): return self.loss

def svc(store): return PortfolioRiskService(store,RiskEngine(DecisionStore()))
def proposal(symbol='BTC/USDT',strategy='s1',price='100',stop='90'):
    return StrategyOrderProposal(symbol=symbol,action='BUY',price=Decimal(price),stop_price=Decimal(stop),strategy_key=strategy)

def test_equity_and_available_capital_include_reservations():
    s=Store(); s.alloc.append(SimpleNamespace(symbol='ETH/USDT',strategy_key='s2',reserved_notional=Decimal('250'),status='reserved'))
    x=svc(s).exposure(); assert x.reserved_capital==Decimal('250'); assert x.available_capital==Decimal('750'); assert x.portfolio_exposure==Decimal('250')

def test_missing_equity_fails_closed():
    s=Store(); s.eq=None
    try: svc(s).exposure(); assert False
    except MissingEquitySnapshot: pass

def test_final_size_is_risk_owned_and_min_max_notional_enforced():
    s=Store(); p=RiskPolicy(maximum_notional=Decimal('300'),minimum_notional=Decimal('50'),max_risk_per_trade=Decimal('1000'))
    d=svc(s).evaluate_and_reserve(proposal(),p); assert d.approved and d.approved_notional==Decimal('300.00000000'); assert d.capital_reserved
    p2=RiskPolicy(maximum_notional=Decimal('40'),minimum_notional=Decimal('50'),max_risk_per_trade=Decimal('1000'))
    d2=svc(Store()).evaluate_and_reserve(proposal(strategy='s2'),p2); assert not d2.approved; assert 'MIN_NOTIONAL_NOT_MET' in d2.rejection_reasons

def test_symbol_strategy_and_portfolio_limits_are_structured():
    s=Store(); s.alloc.append(SimpleNamespace(symbol='BTC/USDT',strategy_key='s1',reserved_notional=Decimal('400'),status='reserved'))
    p=RiskPolicy(max_exposure_per_symbol=Decimal('450'),max_exposure_per_strategy=Decimal('450'),max_total_portfolio_exposure=Decimal('450'),minimum_trade_quantity=Decimal('1'),max_risk_per_trade=Decimal('1000'))
    d=svc(s).evaluate_and_reserve(proposal(),p); assert not d.approved
    assert any(r.code in {'MAX_SYMBOL_EXPOSURE','MAX_STRATEGY_EXPOSURE','MAX_TOTAL_PORTFOLIO_EXPOSURE'} for r in d.rejection_details)

def test_daily_loss_and_drawdown_guards():
    s=Store(equity='800',cash='800',peak='1000'); s.loss=Decimal('-100')
    p=RiskPolicy(max_daily_loss=Decimal('100'),max_drawdown=Decimal('200'))
    d=svc(s).evaluate_and_reserve(proposal(),p); assert not d.approved; assert 'DAILY_LOSS_LIMIT_REACHED' in d.rejection_reasons; assert 'DRAWDOWN_LIMIT_REACHED' in d.rejection_reasons

def test_fixed_and_equity_fraction_sizing():
    p=RiskPolicy(sizing_policy='fixed_notional',fixed_notional=Decimal('200'),max_risk_per_trade=Decimal('1000'))
    d=svc(Store()).evaluate_and_reserve(proposal(),p); assert d.approved_notional==Decimal('200.00000000')
    p=RiskPolicy(sizing_policy='equity_fraction',equity_fraction=Decimal('0.10'),max_risk_per_trade=Decimal('1000'))
    d=svc(Store()).evaluate_and_reserve(proposal(strategy='s2'),p); assert d.approved_notional==Decimal('100.00000000')

def test_concurrent_requests_cannot_overallocate_cash():
    s=Store(equity='100',cash='100',peak='100'); policy=RiskPolicy(max_risk_per_trade=Decimal('1000'),maximum_notional=Decimal('80'),minimum_available_balance=Decimal('0.01'))
    out=[]
    def run(i): out.append(svc(s).evaluate_and_reserve(proposal(symbol=f'S{i}/USDT',strategy=f's{i}',price='1',stop='0.5'),policy))
    ts=[Thread(target=run,args=(i,)) for i in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    approved=[d for d in out if d.approved]; assert sum(d.approved_notional for d in approved)<=Decimal('100'); assert len(approved)==2
    # first reserves 80, second is resized to remaining 20; never 160
    assert sorted(d.approved_notional for d in approved)==[Decimal('20.00000000'),Decimal('80.00000000')]

def test_max_concurrent_positions_counts_pending_allocations():
    s=Store(); s.alloc.append(SimpleNamespace(symbol='A/USDT',strategy_key='s0',reserved_notional=Decimal('10'),status='reserved'))
    p=RiskPolicy(max_open_positions=1,max_risk_per_trade=Decimal('1000'),minimum_trade_quantity=Decimal('1'))
    d=svc(s).evaluate_and_reserve(proposal(symbol='B/USDT',price='1',stop='0.5'),p); assert not d.approved; assert 'MAX_OPEN_POSITIONS_REACHED' in d.rejection_reasons
