from __future__ import annotations

import inspect
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier, Lock
from types import SimpleNamespace
from uuid import uuid4
from pathlib import Path

API_ROOT = Path.cwd() / 'apps/api'

import pytest

from packages.exchange.demo import DemoOrderEngine
from packages.exchange.execution import (
    AccountCapabilities, ExecutionGateway, ExecutionMode, ExecutionResult,
    ExchangePreflightTimeoutError, ExchangeRateLimitError, UnknownOrderStateError,
)
from packages.exchange.models import DemoOrderSubmitRequest, OrderStatus
from packages.portfolio.models import EquitySnapshot
from packages.portfolio.service import PortfolioRiskService
from packages.reconciliation.service import WorkerLeaseService
from packages.risk.engine import RiskEngine
from packages.risk.models import OrderAction, RiskDecision, RiskPolicy, StrategyOrderProposal
from packages.safety.models import CircuitBreakerType, SafetyHaltRequest, SafetyScope, SafetyState
from packages.safety.service import SafetyControlService, SafetyHaltError
from strategies import RSITransitionStrategy, MACDCrossoverStrategy, MACrossoverStrategy


class DecisionStore:
    def __init__(self): self.by_fp={}; self.by_id={}
    def get_by_fingerprint(self, fp): return self.by_fp.get(fp)
    def save(self, fp, d):
        old=self.by_fp.get(fp)
        if old: return old
        self.by_fp[fp]=d; self.by_id[str(d.id)]=d; return d
    def mark_capital_reserved(self, d): d.capital_reserved=True; return d

class FakeDB:
    def commit(self): pass

class AllocationStore:
    def __init__(self, cash='1000'):
        self.eq=EquitySnapshot(equity=Decimal(cash), cash_balance=Decimal(cash), peak_equity=Decimal(cash))
        self.alloc=[]; self.positions=[]; self.lock=Lock(); self.db=FakeDB()
    @contextmanager
    def allocation_lock(self):
        with self.lock: yield
    def latest_equity(self): return self.eq
    def open_positions(self): return list(self.positions)
    def active_allocations(self): return list(self.alloc)
    def reserve(self, d):
        row=SimpleNamespace(risk_decision_id=d.id,symbol=d.proposal.symbol,strategy_key=d.proposal.strategy_key,reserved_notional=d.approved_notional,status='reserved')
        self.alloc.append(row); return row
    def daily_realized_pnl(self, start): return Decimal('0')

class MemoryRiskStore:
    requires_capital_reservation=True
    def __init__(self, d): self.d=d
    def get(self, _): return self.d

class AtomicOrderStore:
    def __init__(self): self.lock=Lock(); self.order=None
    def get_by_risk_decision(self, rid):
        with self.lock: return self.order if self.order and self.order.risk_decision_id==rid else None
    def create(self, order):
        with self.lock:
            if self.order is not None: return self.order, False
            self.order=order; return order, True
    def update(self, order):
        with self.lock: self.order=order; return order
    def list(self, limit=100, offset=0): return [self.order] if self.order else []
    def get(self, oid): return self.order if self.order and str(self.order.id)==str(oid) else None

class Adapter:
    mode=ExecutionMode.DEMO
    def __init__(self, behavior='open', barrier=None): self.behavior=behavior; self.calls=0; self.preflight=0; self.barrier=barrier
    def validate_account_capabilities(self):
        self.preflight += 1
        if self.behavior=='preflight_timeout_once' and self.preflight==1: raise ExchangePreflightTimeoutError('timeout')
        if self.behavior=='preflight_rate_once' and self.preflight==1: raise ExchangeRateLimitError('rate')
        return AccountCapabilities(authenticated=True,can_trade=True,supports_client_order_id=True)
    def submit_order(self, order):
        self.calls += 1
        if self.barrier: self.barrier.wait()
        if self.behavior=='unknown': raise UnknownOrderStateError('ambiguous')
        return ExecutionResult(exchange_order_id='ex-1',status=OrderStatus.OPEN)
    def find_order_by_client_id(self, client_order_id, symbol): return None

class SafetyStore:
    def __init__(self): self.state=SafetyState(); self.commands={}; self.events=[]; self.lock=Lock()
    @contextmanager
    def locked_state(self):
        with self.lock: yield self.state
    def load_state(self): return self.state.model_copy(deep=True)
    def save_state(self, s): self.state=s.model_copy(deep=True)
    def get_command(self,k): return self.commands.get(k)
    def save_command(self,k,a,r,res): self.commands[k]={'result':res}
    def append_event(self,e): self.events.append(e); return e
    def history(self,limit=100,offset=0): return self.events[offset:offset+limit]

class LeaseStore:
    def __init__(self): self.leases={}; self.lock=Lock()
    @contextmanager
    def locked_lease(self, bot_id):
        with self.lock: yield self.leases.get(bot_id)
    def load_lease(self,b): return self.leases.get(b)
    def create_lease(self,l):
        if l.bot_id in self.leases: return None
        self.leases[l.bot_id]=l; return l
    def save_lease(self,l): self.leases[l.bot_id]=l; return l
    def delete_lease(self,b): self.leases.pop(b,None)


def proposal(i=0):
    return StrategyOrderProposal(symbol=f'S{i}/USDT',action='BUY',price=Decimal('1'),stop_price=Decimal('0.5'),strategy_key=f's{i}')

def approved_decision():
    p=StrategyOrderProposal(symbol='BTC/USDT',action=OrderAction.BUY,price=Decimal('100'),stop_price=Decimal('90'),strategy_key='alpha')
    return RiskDecision(proposal=p,approved=True,approved_quantity=Decimal('1'),approved_notional=Decimal('100'),risk_amount=Decimal('10'),policy_snapshot={},capital_reserved=True)

def engine_for(adapter, safety=None):
    d=approved_decision(); store=AtomicOrderStore()
    return d,store,DemoOrderEngine(MemoryRiskStore(d),store,trading_mode='demo',gateway=ExecutionGateway(adapter,mode='demo',max_safe_retries=2,retry_delay_seconds=0),safety_service=safety)


def test_concurrent_order_proposals_never_overallocate():
    store=AllocationStore('1000'); risk=RiskEngine(DecisionStore()); svc=PortfolioRiskService(store,risk)
    policy=RiskPolicy(max_risk_per_trade=Decimal('1000'),maximum_notional=Decimal('80'),minimum_available_balance=Decimal('0.01'))
    with ThreadPoolExecutor(max_workers=20) as pool:
        out=list(pool.map(lambda i: svc.evaluate_and_reserve(proposal(i),policy), range(20)))
    approved=[d for d in out if d.approved]
    assert sum(d.approved_notional for d in approved) <= Decimal('1000')
    assert sum(a.reserved_notional for a in store.alloc) <= Decimal('1000')


def test_duplicate_api_command_is_idempotent_under_concurrency():
    safety=SafetyControlService(SafetyStore()); barrier=Barrier(8)
    req=SafetyHaltRequest(idempotency_key='same-api-request',scope=SafetyScope.GLOBAL,reason_code='operator_halt',operator_id='ops')
    def call(_): barrier.wait(); return safety.halt(req)
    with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(call,range(8)))
    assert sum(not r.idempotent_replay for r in results)==1
    assert len(safety.store.events)==1


def test_duplicate_worker_processing_blocked_by_durable_lease():
    now=[datetime(2026,1,1,tzinfo=timezone.utc)]; leases=WorkerLeaseService(LeaseStore(),ttl_seconds=30,now_fn=lambda:now[0])
    barrier=Barrier(2)
    def acquire(worker): barrier.wait(); return leases.acquire('bot-a',worker)
    with ThreadPoolExecutor(max_workers=2) as pool: out=list(pool.map(acquire,['w1','w2']))
    assert sum(x.acquired for x in out)==1
    assert sum(not x.acquired for x in out)==1


def test_risk_allocation_race_is_serialized_without_sleep():
    store=AllocationStore('100'); policy=RiskPolicy(max_risk_per_trade=Decimal('1000'),maximum_notional=Decimal('80'),minimum_available_balance=Decimal('0.01'))
    barrier=Barrier(2)
    def run(i): barrier.wait(); return PortfolioRiskService(store,RiskEngine(DecisionStore())).evaluate_and_reserve(proposal(i),policy)
    with ThreadPoolExecutor(max_workers=2) as pool: out=list(pool.map(run,[1,2]))
    assert sorted(d.approved_notional for d in out if d.approved)==[Decimal('20.00000000'),Decimal('80.00000000')]


def test_order_store_contract_has_database_conflict_recovery():
    src=(API_ROOT/'packages/exchange/storage.py').read_text().split('def create(self, order',1)[1].split('def update',1)[0]
    assert 'IntegrityError' in src and 'rollback()' in src and 'get_by_risk_decision' in src


def test_redis_temporary_unavailability_is_non_authoritative():
    root=API_ROOT/'packages'
    authoritative='\n'.join((root/n).read_text() for n in ['portfolio/storage.py','reconciliation/storage.py','safety/storage.py'])
    assert 'redis' not in authoritative.lower()


@pytest.mark.parametrize('behavior', ['preflight_timeout_once','preflight_rate_once'])
def test_preflight_timeout_and_rate_limit_retry_only_read_only_check(behavior):
    adapter=Adapter(behavior); d,_,engine=engine_for(adapter)
    order=engine.submit(DemoOrderSubmitRequest(risk_decision_id=d.id))
    assert order.status is OrderStatus.OPEN
    assert adapter.preflight==2
    assert adapter.calls==1


def test_unknown_order_submission_result_is_never_retried():
    adapter=Adapter('unknown'); d,_,engine=engine_for(adapter); req=DemoOrderSubmitRequest(risk_decision_id=d.id)
    first=engine.submit(req); second=engine.submit(req)
    assert first.status is OrderStatus.UNKNOWN and first.reconciliation_required
    assert second.id==first.id and adapter.calls==1


def test_worker_crash_restart_allows_only_expired_lease_takeover():
    now=[datetime(2026,1,1,tzinfo=timezone.utc)]; service=WorkerLeaseService(LeaseStore(),ttl_seconds=10,now_fn=lambda:now[0])
    first=service.acquire('bot','worker-a'); assert first.acquired
    assert not service.acquire('bot','worker-b').acquired
    now[0]+=timedelta(seconds=11)
    takeover=service.acquire('bot','worker-b'); assert takeover.acquired and takeover.lease.lease_token!=first.lease.lease_token


def test_api_restart_does_not_own_or_destroy_worker_lease_state():
    store=LeaseStore(); now=datetime(2026,1,1,tzinfo=timezone.utc)
    worker=WorkerLeaseService(store,ttl_seconds=30,now_fn=lambda:now).acquire('bot','worker-a').lease
    # Reconstructing the service simulates API/process lifecycle independence; durable lease remains.
    after_api_restart=WorkerLeaseService(store,ttl_seconds=30,now_fn=lambda:now)
    seen=store.load_lease('bot')
    assert seen.lease_token==worker.lease_token
    assert not after_api_restart.acquire('bot','api-process').acquired


def test_database_engine_uses_pre_ping_for_postgresql_reconnect():
    src=(API_ROOT/'database.py').read_text()
    assert 'pool_pre_ping=True' in src



def test_reconciliation_after_simulated_failure_recovers_without_resubmission():
    # UNKNOWN submission is persisted once; reconciliation is read-only and must not resubmit.
    adapter=Adapter('unknown'); d,store,engine=engine_for(adapter); req=DemoOrderSubmitRequest(risk_decision_id=d.id)
    failed=engine.submit(req)
    assert failed.status is OrderStatus.UNKNOWN and adapter.calls==1
    adapter.behavior='open'
    def recovered(client_order_id, symbol):
        return ExecutionResult(exchange_order_id='ex-recovered',status=OrderStatus.FILLED,filled_quantity=Decimal('1'))
    adapter.find_order_by_client_id=recovered
    result=engine.reconcile(failed.id)
    assert result.status is OrderStatus.FILLED
    assert adapter.calls==1
    assert result.exchange_order_id=='ex-recovered'

def test_circuit_breaker_activation_blocks_new_order():
    safety=SafetyControlService(SafetyStore(),thresholds={CircuitBreakerType.EXCHANGE_CONNECTIVITY:1})
    safety.record_failure(CircuitBreakerType.EXCHANGE_CONNECTIVITY,reason_code='timeout')
    adapter=Adapter(); d,_,engine=engine_for(adapter,safety)
    with pytest.raises(SafetyHaltError): engine.submit(DemoOrderSubmitRequest(risk_decision_id=d.id))
    assert adapter.calls==0


def test_kill_switch_wins_against_concurrent_new_entries():
    safety=SafetyControlService(SafetyStore()); safety.halt(SafetyHaltRequest(idempotency_key='halt-now',scope=SafetyScope.GLOBAL,reason_code='ops',operator_id='ops'))
    adapter=Adapter(); d,_,engine=engine_for(adapter,safety); barrier=Barrier(16)
    def submit(_):
        barrier.wait()
        try: engine.submit(DemoOrderSubmitRequest(risk_decision_id=d.id)); return 'executed'
        except SafetyHaltError: return 'blocked'
    with ThreadPoolExecutor(max_workers=16) as pool: result=list(pool.map(submit,range(16)))
    assert set(result)=={'blocked'} and adapter.calls==0


def test_high_volume_closed_candle_strategy_evaluation_is_fast_and_has_no_execution_boundary():
    candles=[]
    for i in range(1000):
        p=100+(i%17)*0.1
        candles.append({'open':p-0.1,'high':p+0.2,'low':p-0.2,'close':p})
    strategies=[RSITransitionStrategy(),MACDCrossoverStrategy(),MACrossoverStrategy()]
    start=time.perf_counter()
    decisions=0
    for _ in range(100):
        for strat in strategies:
            out=strat.on_candle_closed(candles); assert out['decision'] in {'BUY','SELL','HOLD'}; decisions+=1
    elapsed=time.perf_counter()-start
    assert decisions==300
    assert elapsed < 5.0  # generous CPU-only regression guard, no network/DB timing involved
    source='\n'.join(inspect.getsource(type(s)) for s in strategies)
    assert 'ExecutionGateway' not in source and 'create_order' not in source and 'submit_order' not in source


@pytest.mark.skip(reason='Runtime-required: repository has no WebSocket transport/client to exercise disconnect/reconnect without inventing production behavior.')
def test_websocket_disconnect_reconnect_runtime_required():
    pass

@pytest.mark.skip(reason='Integration-required: needs real PostgreSQL to prove serialization/deadlock/transaction-conflict behavior, unavailable in this sandbox.')
def test_real_postgresql_transaction_conflict_integration():
    pass

@pytest.mark.skip(reason='Runtime-required: needs a running PostgreSQL instance to terminate/recreate a backend connection and prove pool reconnect behavior.')
def test_real_postgresql_disconnect_reconnect_runtime_required():
    pass

@pytest.mark.skip(reason='Integration-required: needs a running Redis/Valkey instance to interrupt/restart connectivity; Redis is transient and not authoritative.')
def test_real_redis_disconnect_reconnect_integration():
    pass
