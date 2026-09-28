from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import sys, types
_research_service = types.ModuleType("packages.research.service")
_research_service.observe_best_effort = lambda *args, **kwargs: None
sys.modules.setdefault("packages.research.service", _research_service)

from packages.exchange.execution import ExecutionResult
from packages.exchange.models import DemoOrder, OrderStatus, OrderType
from packages.positions.engine import PositionEngine
from packages.positions.models import Position, PositionSide, PositionStatus
from packages.protection.models import PositionProtection, ProtectionStatus
from packages.reconciliation.models import DiscrepancyStatus, ExchangePositionSnapshot
from packages.reconciliation.service import ReconciliationService, WorkerLeaseService
from packages.safety.models import CircuitBreakerType, CircuitBreakerState, SafetyHaltRequest, SafetyScope


class MemoryOrderStore:
    def __init__(self, orders): self.orders={str(o.id):o for o in orders}; self.updates=0
    def list(self, limit=5000, offset=0): return list(self.orders.values())[offset:offset+limit]
    def update(self,o): self.orders[str(o.id)]=o; self.updates+=1; return o

class MemoryPositionStore:
    def __init__(self, positions=None): self.positions={str(p.id):p for p in positions or []}; self.fills={}; self.db=None
    def get(self,id): return self.positions.get(str(id))
    def get_open_for_symbol(self,symbol): return next((p for p in self.positions.values() if p.symbol==symbol and p.status is PositionStatus.OPEN),None)
    def save(self,p): self.positions[str(p.id)]=p; return p
    def claim_fill(self,order_id,position_id):
        k=str(order_id)
        if k in self.fills:return False
        self.fills[k]=str(position_id);return True
    def get_position_for_fill(self,order_id):
        pid=self.fills.get(str(order_id)); return self.positions.get(pid) if pid else None
    def list(self,limit=5000,offset=0): return list(self.positions.values())[offset:offset+limit]

class MemoryReconStore:
    def __init__(self): self._runs=[]; self._issues=[]; self._leases={}
    def create_run(self,r): self._runs.append(r); return r
    def save_run(self,r): return r
    def latest_run(self,bot_id='demo-bot'): return next((r for r in reversed(self._runs) if r.bot_id==bot_id),None)
    def runs(self,limit=100,offset=0): return list(reversed(self._runs))[offset:offset+limit]
    def add_discrepancy(self,d): self._issues.append(d); return d
    def discrepancies(self,run_id=None,unresolved_only=False,limit=200,offset=0):
        xs=[x for x in self._issues if run_id is None or str(x.run_id)==str(run_id)]
        if unresolved_only: xs=[x for x in xs if x.status.value=='open']
        return list(reversed(xs))[offset:offset+limit]
    def severe_unresolved_count(self): return sum(x.severity.value=='severe' and x.status.value=='open' for x in self._issues)
    def resolve_open_severe(self):
        n=0
        for x in self._issues:
            if x.severity.value=='severe' and x.status.value=='open': x.status=DiscrepancyStatus.RESOLVED;x.resolved_at=datetime.now(timezone.utc);n+=1
        return n
    class Ctx:
        def __init__(self,store,bot):self.s=store;self.bot=bot
        def __enter__(self):return self.s._leases.get(self.bot)
        def __exit__(self,*a):return False
    def locked_lease(self,bot_id): return self.Ctx(self,bot_id)
    def load_lease(self,bot_id): return self._leases.get(bot_id)
    def create_lease(self,l):
        if l.bot_id in self._leases:return None
        self._leases[l.bot_id]=l;return l
    def save_lease(self,l):self._leases[l.bot_id]=l;return l
    def delete_lease(self,bot_id):self._leases.pop(bot_id,None)

class FakeSafety:
    def __init__(self):self.breakers={};self.halts=[]
    def halt(self,r:SafetyHaltRequest):
        self.halts.append(r)
        b=self.breakers.setdefault(r.scope_key,CircuitBreakerState(breaker=CircuitBreakerType(r.scope_key),threshold=3))
        b.open=True;b.reason_code=r.reason_code;b.recovery_observed=False
    def record_success(self,t):
        b=self.breakers.setdefault(t.value,CircuitBreakerState(breaker=t,threshold=3));b.last_success_at=datetime.now(timezone.utc)
        if b.open:b.recovery_observed=True
        else:b.failure_count=0
        return b
    def record_failure(self,t,reason_code):
        b=self.breakers.setdefault(t.value,CircuitBreakerState(breaker=t,threshold=3));b.failure_count+=1;return b

class FakeProtection:
    def __init__(self, rows=None):self.rows=rows or [];self.calls=0
    def reconcile(self):self.calls+=1;return self.rows

class Reader:
    def __init__(self, mapping=None, positions=None):self.mapping=mapping or {};self.positions=positions;self.lookups=[]
    def lookup_order(self,o):self.lookups.append(o.client_order_id);return self.mapping.get(o.client_order_id)
    def open_positions(self):return self.positions


def order(status=OrderStatus.OPEN, filled='0', symbol='BTC/USDT'):
    return DemoOrder(risk_decision_id=uuid4(),client_order_id=f'cid-{uuid4().hex}',exchange_order_id='ex-1',symbol=symbol,strategy_key='s',side='BUY',type=OrderType.LIMIT,quantity=Decimal('2'),price=Decimal('100'),filled_quantity=Decimal(filled),status=status)


def service(orders,reader,positions=None,protection=None,safety=None):
    os=MemoryOrderStore(orders); ps=MemoryPositionStore(positions); pe=PositionEngine(ps); rs=MemoryReconStore(); sf=safety or FakeSafety()
    return ReconciliationService(rs,os,pe,protection or FakeProtection(),reader,sf),os,ps,rs,sf


def test_order_recovery_matrix_and_partial_fill():
    rows=[order(OrderStatus.OPEN),order(OrderStatus.OPEN),order(OrderStatus.OPEN),order(OrderStatus.OPEN),order(OrderStatus.OPEN)]
    states=[
        ExecutionResult(exchange_order_id='a',status=OrderStatus.OPEN),
        ExecutionResult(exchange_order_id='b',status=OrderStatus.PARTIALLY_FILLED,filled_quantity=Decimal('1')),
        ExecutionResult(exchange_order_id='c',status=OrderStatus.FILLED,filled_quantity=Decimal('2')),
        ExecutionResult(exchange_order_id='d',status=OrderStatus.CANCELED),
        ExecutionResult(exchange_order_id='e',status=OrderStatus.REJECTED),
    ]
    reader=Reader(dict(zip([o.client_order_id for o in rows],states)),positions=[ExchangePositionSnapshot(symbol='BTC/USDT',side='long',quantity=Decimal('2'))])
    svc,os,ps,_,_=service(rows,reader)
    run=svc.run()
    assert [o.status for o in rows]==[OrderStatus.OPEN,OrderStatus.PARTIALLY_FILLED,OrderStatus.FILLED,OrderStatus.CANCELED,OrderStatus.REJECTED]
    assert len(ps.fills)==1
    assert run.discrepancy_count>=4


def test_filled_recovery_is_idempotent_after_crash_restart():
    o=order(OrderStatus.UNKNOWN)
    reader=Reader({o.client_order_id:ExecutionResult(exchange_order_id='ex',status=OrderStatus.FILLED,filled_quantity=Decimal('2'))},positions=[ExchangePositionSnapshot(symbol='BTC/USDT',side='long',quantity=Decimal('2'))])
    svc,_,ps,_,_=service([o],reader)
    first=svc.run(trigger='startup')
    pos=list(ps.positions.values())[0]
    qty=pos.quantity
    second=svc.run(trigger='startup')
    assert len(ps.positions)==1
    assert list(ps.positions.values())[0].quantity==qty==Decimal('2')
    assert len(ps.fills)==1
    assert first.id!=second.id


def test_ambiguous_active_order_creates_severe_discrepancy_and_immediate_halt():
    o=order(OrderStatus.UNKNOWN)
    svc,_,_,store,safety=service([o],Reader({},positions=[]))
    run=svc.run()
    assert run.status.value=='blocked'
    assert run.severe_unresolved_count>=1
    assert store.severe_unresolved_count()>=1
    breaker=safety.breakers[CircuitBreakerType.RECONCILIATION_FAILURE.value]
    assert breaker.open is True
    assert safety.halts[0].reason_code=='severe_reconciliation_discrepancy'


def test_healthy_restart_marks_recovery_but_does_not_auto_resume_severe_halt():
    o=order(OrderStatus.UNKNOWN)
    reader=Reader({},positions=[])
    svc,_,_,store,safety=service([o],reader)
    svc.run()
    reader.mapping[o.client_order_id]=ExecutionResult(exchange_order_id='ex',status=OrderStatus.CANCELED)
    healthy=svc.run()
    breaker=safety.breakers[CircuitBreakerType.RECONCILIATION_FAILURE.value]
    assert healthy.severe_unresolved_count==0
    assert store.severe_unresolved_count()==0
    assert breaker.open is True
    assert breaker.recovery_observed is True


def test_open_position_mismatch_and_closed_position_present_are_severe():
    openp=Position(symbol='ETH/USDT',strategy_key='s',side=PositionSide.LONG,quantity=Decimal('2'),average_entry_price=Decimal('10'),current_price=Decimal('10'))
    closed=Position(symbol='BTC/USDT',strategy_key='s',side=PositionSide.LONG,quantity=Decimal('0'),average_entry_price=Decimal('100'),current_price=Decimal('90'),status=PositionStatus.CLOSED)
    reader=Reader({},positions=[ExchangePositionSnapshot(symbol='ETH/USDT',side='long',quantity=Decimal('1')),ExchangePositionSnapshot(symbol='BTC/USDT',side='long',quantity=Decimal('1'))])
    svc,_,_,store,_=service([],reader,[openp,closed])
    run=svc.run()
    kinds={d.kind for d in store.discrepancies(run_id=run.id)}
    assert 'position_state_mismatch' in kinds
    assert 'closed_position_still_open' in kinds
    assert run.severe_unresolved_count==2


def test_protection_failure_is_severe_but_protection_recovery_remains_callable():
    p=PositionProtection(position_id=uuid4(),tp_price=Decimal('120'),sl_price=Decimal('90'),protection_status=ProtectionStatus.MISSING,error_reason='missing')
    prot=FakeProtection([p])
    svc,_,_,store,_=service([],Reader({},positions=[]),protection=prot)
    run=svc.run()
    assert prot.calls==1
    assert any(d.kind=='protection_not_fully_recovered' for d in store.discrepancies(run_id=run.id))
    assert run.status.value=='blocked'


def test_worker_lease_blocks_second_worker_and_allows_expired_takeover():
    store=MemoryReconStore(); now=[datetime(2026,1,1,tzinfo=timezone.utc)]
    leases=WorkerLeaseService(store,ttl_seconds=10,now_fn=lambda:now[0])
    a=leases.acquire('bot','worker-a'); assert a.acquired
    b=leases.acquire('bot','worker-b'); assert not b.acquired and b.reason_code=='lease_owned_by_active_worker'
    now[0]+=timedelta(seconds=11)
    b2=leases.acquire('bot','worker-b'); assert b2.acquired and b2.lease.worker_id=='worker-b'
    assert b2.lease.lease_token!=a.lease.lease_token


def test_worker_heartbeat_requires_owner_and_unexpired_token():
    store=MemoryReconStore(); now=[datetime(2026,1,1,tzinfo=timezone.utc)]
    leases=WorkerLeaseService(store,ttl_seconds=10,now_fn=lambda:now[0])
    a=leases.acquire('bot','worker-a').lease
    now[0]+=timedelta(seconds=3)
    hb=leases.heartbeat('bot','worker-a',a.lease_token)
    assert hb.expires_at==now[0]+timedelta(seconds=10)
    try: leases.heartbeat('bot','worker-b',a.lease_token)
    except RuntimeError as exc: assert str(exc)=='worker_lease_not_owned'
    else: raise AssertionError('non-owner heartbeat accepted')


def test_recovery_reader_interface_has_no_submission_operation():
    assert not hasattr(Reader(), 'submit')


def test_reconciliation_package_has_no_redis_authority():
    from pathlib import Path
    root=Path(__file__).parents[1]/'packages'/'reconciliation'
    text='\n'.join(p.read_text() for p in root.glob('*.py'))
    assert 'redis' not in text.lower()
