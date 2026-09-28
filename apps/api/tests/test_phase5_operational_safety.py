from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest

from packages.exchange.demo import DemoOrderEngine
from packages.exchange.execution import AccountCapabilities, ExecutionGateway, ExecutionMode, ExecutionResult
from packages.exchange.models import DemoOrder, DemoOrderSubmitRequest, OrderStatus, OrderType
from packages.risk.models import OrderAction, RiskDecision, StrategyOrderProposal
from packages.safety.models import (
    CircuitBreakerType,
    HaltMode,
    SafetyAuditEvent,
    SafetyHaltRequest,
    SafetyResumeRequest,
    SafetyScope,
    SafetyState,
)
from packages.safety.service import SafetyControlService, SafetyHaltError, UnsafeResumeError


class MemorySafetyStore:
    def __init__(self):
        self.state = SafetyState()
        self.commands = {}
        self.events = []

    @contextmanager
    def locked_state(self):
        yield self.state

    def load_state(self):
        return self.state.model_copy(deep=True)

    def save_state(self, state):
        self.state = state.model_copy(deep=True)

    def get_command(self, key):
        return deepcopy(self.commands.get(key))

    def save_command(self, key, action, request, result):
        self.commands[key] = {"action": action, "request": deepcopy(request), "result": deepcopy(result)}

    def append_event(self, event: SafetyAuditEvent):
        self.events.append(event.model_copy(deep=True))
        return event

    def history(self, limit=100, offset=0):
        return list(reversed(self.events))[offset:offset + limit]


class RiskStore:
    requires_capital_reservation = True

    def __init__(self, decision):
        self.decision = decision

    def get(self, _):
        return self.decision


class OrderStore:
    def __init__(self):
        self.orders = {}

    def get_by_risk_decision(self, decision_id):
        return next((o for o in self.orders.values() if o.risk_decision_id == decision_id), None)

    def create(self, order):
        self.orders[str(order.id)] = order
        return order, True

    def update(self, order):
        self.orders[str(order.id)] = order
        return order

    def get(self, order_id):
        return self.orders.get(str(order_id))


class CountingAdapter:
    mode = ExecutionMode.DEMO

    def __init__(self):
        self.submissions = 0
        self.reconciliations = 0

    def validate_account_capabilities(self):
        return AccountCapabilities(authenticated=True, can_trade=True, supports_client_order_id=True)

    def submit_order(self, order):
        self.submissions += 1
        return ExecutionResult(exchange_order_id="demo-1", status=OrderStatus.OPEN)

    def find_order_by_client_id(self, client_order_id, symbol):
        self.reconciliations += 1
        return ExecutionResult(exchange_order_id="demo-1", status=OrderStatus.OPEN)


def decision(symbol="BTC/USDT", strategy="alpha"):
    proposal = StrategyOrderProposal(symbol=symbol, action=OrderAction.BUY, price=Decimal("100"), strategy_key=strategy)
    return RiskDecision(
        proposal=proposal,
        approved=True,
        approved_quantity=Decimal("1"),
        approved_notional=Decimal("100"),
        risk_amount=Decimal("10"),
        policy_snapshot={},
        capital_reserved=True,
    )


def halt(service, scope=SafetyScope.GLOBAL, key=None, mode=HaltMode.HALTED, reason="operator_halt", idem="halt-command-001"):
    return service.halt(SafetyHaltRequest(idempotency_key=idem, scope=scope, scope_key=key, mode=mode, reason_code=reason, operator_id="ops"))


def resume(service, scope=SafetyScope.GLOBAL, key=None, idem="resume-command-001"):
    return service.resume(SafetyResumeRequest(idempotency_key=idem, scope=scope, scope_key=key, operator_id="ops", acknowledgement="conditions verified"))


def test_global_halt_blocks_order_before_exchange():
    store = MemorySafetyStore()
    safety = SafetyControlService(store)
    halt(safety)
    d = decision()
    adapter = CountingAdapter()
    engine = DemoOrderEngine(RiskStore(d), OrderStore(), trading_mode="demo", gateway=ExecutionGateway(adapter, mode="demo"), safety_service=safety)

    with pytest.raises(SafetyHaltError):
        engine.submit(DemoOrderSubmitRequest(risk_decision_id=d.id))

    assert adapter.submissions == 0
    assert engine.order_store.orders == {}


def test_restart_preserves_durable_halt_state():
    store = MemorySafetyStore()
    SafetyControlService(store).halt(SafetyHaltRequest(idempotency_key="restart-halt-001", scope=SafetyScope.SYMBOL, scope_key="btc/usdt", reason_code="venue_anomaly", operator_id="ops"))

    restarted = SafetyControlService(store)
    status = restarted.status(symbol="BTC/USDT")

    assert status.trading_halted is True
    assert status.blockers[0].scope is SafetyScope.SYMBOL
    assert status.blockers[0].scope_key == "BTC/USDT"


def test_halt_and_resume_commands_are_idempotent_and_audited():
    store = MemorySafetyStore()
    safety = SafetyControlService(store)
    first = halt(safety, idem="same-halt-key")
    replay = halt(safety, idem="same-halt-key")

    assert first.applied is True
    assert replay.idempotent_replay is True
    assert len([e for e in store.events if e.event_type == "safety.halt"]) == 1

    resumed = resume(safety, idem="same-resume-key")
    replay_resume = resume(safety, idem="same-resume-key")
    assert resumed.active is False
    assert replay_resume.idempotent_replay is True
    assert len([e for e in store.events if e.event_type == "safety.resume"]) == 1


def test_per_bot_pause_and_disable_and_symbol_halt_are_scoped():
    store = MemorySafetyStore()
    safety = SafetyControlService(store)
    halt(safety, SafetyScope.BOT, "bot-a", HaltMode.PAUSED, idem="pause-bot-a")
    halt(safety, SafetyScope.BOT, "bot-b", HaltMode.DISABLED, idem="disable-bot-b")
    halt(safety, SafetyScope.SYMBOL, "ETH/USDT", idem="halt-eth-001")

    with pytest.raises(SafetyHaltError):
        safety.require_new_entry_allowed(bot_id="bot-a", symbol="BTC/USDT")
    with pytest.raises(SafetyHaltError):
        safety.require_new_entry_allowed(bot_id="bot-b", symbol="BTC/USDT")
    with pytest.raises(SafetyHaltError):
        safety.require_new_entry_allowed(bot_id="bot-c", symbol="ETH/USDT")
    safety.require_new_entry_allowed(bot_id="bot-c", symbol="BTC/USDT")


def test_circuit_breaker_threshold_opens_and_does_not_auto_resume():
    store = MemorySafetyStore()
    safety = SafetyControlService(store, thresholds={CircuitBreakerType.EXCHANGE_CONNECTIVITY: 2})

    safety.record_failure(CircuitBreakerType.EXCHANGE_CONNECTIVITY, reason_code="exchange_unreachable")
    assert safety.circuits()[0].open is False
    safety.record_failure(CircuitBreakerType.EXCHANGE_CONNECTIVITY, reason_code="exchange_unreachable")
    assert safety.circuits()[0].open is True

    safety.record_success(CircuitBreakerType.EXCHANGE_CONNECTIVITY)
    breaker = {b.breaker: b for b in safety.circuits()}[CircuitBreakerType.EXCHANGE_CONNECTIVITY]
    assert breaker.open is True
    assert breaker.recovery_observed is True

    resume(safety, SafetyScope.CIRCUIT, CircuitBreakerType.EXCHANGE_CONNECTIVITY.value, idem="resume-connectivity")
    assert {b.breaker: b for b in safety.circuits()}[CircuitBreakerType.EXCHANGE_CONNECTIVITY].open is False


def test_severe_circuit_resume_requires_recovery_observation():
    store = MemorySafetyStore()
    safety = SafetyControlService(store)
    safety.enforce_market_data_freshness(age_seconds=120, max_age_seconds=30)

    with pytest.raises(UnsafeResumeError):
        resume(safety, SafetyScope.CIRCUIT, CircuitBreakerType.STALE_MARKET_DATA.value, idem="resume-stale-too-soon")

    safety.enforce_market_data_freshness(age_seconds=1, max_age_seconds=30)
    assert {b.breaker: b for b in safety.circuits()}[CircuitBreakerType.STALE_MARKET_DATA].open is True
    resume(safety, SafetyScope.CIRCUIT, CircuitBreakerType.STALE_MARKET_DATA.value, idem="resume-stale-safe")


def test_drawdown_stale_data_and_clock_drift_open_safety_halts():
    store = MemorySafetyStore()
    safety = SafetyControlService(store)
    safety.enforce_drawdown(current_equity=Decimal("80"), peak_equity=Decimal("100"), max_drawdown=Decimal("10"))
    safety.enforce_market_data_freshness(age_seconds=31, max_age_seconds=30)
    safety.enforce_clock_drift(drift_seconds=6, max_drift_seconds=5)

    opened = {b.breaker for b in safety.circuits() if b.open}
    assert CircuitBreakerType.DRAWDOWN in opened
    assert CircuitBreakerType.STALE_MARKET_DATA in opened
    assert CircuitBreakerType.CLOCK_DRIFT in opened
    with pytest.raises(SafetyHaltError):
        safety.require_new_entry_allowed(bot_id="demo-bot", symbol="BTC/USDT")


def test_reconciliation_remains_available_while_new_entries_are_halted():
    store = MemorySafetyStore()
    safety = SafetyControlService(store)
    halt(safety)
    d = decision()
    adapter = CountingAdapter()
    orders = OrderStore()
    existing = DemoOrder(
        risk_decision_id=d.id,
        client_order_id="ord-existing",
        exchange_order_id="demo-1",
        symbol=d.proposal.symbol,
        strategy_key=d.proposal.strategy_key,
        side="BUY",
        type=OrderType.LIMIT,
        quantity=Decimal("1"),
        price=Decimal("100"),
        status=OrderStatus.UNKNOWN,
        reconciliation_required=True,
    )
    orders.orders[str(existing.id)] = existing
    engine = DemoOrderEngine(RiskStore(d), orders, trading_mode="demo", gateway=ExecutionGateway(adapter, mode="demo"), safety_service=safety)

    reconciled = engine.reconcile(existing.id)

    assert adapter.reconciliations == 1
    assert adapter.submissions == 0
    assert reconciled.status is OrderStatus.OPEN


def test_reconciliation_failures_open_breaker_at_configured_threshold():
    store = MemorySafetyStore()
    safety = SafetyControlService(store, thresholds={CircuitBreakerType.RECONCILIATION_FAILURE: 2})
    safety.record_failure(CircuitBreakerType.RECONCILIATION_FAILURE, reason_code="mismatch")
    safety.record_failure(CircuitBreakerType.RECONCILIATION_FAILURE, reason_code="mismatch")

    breaker = {b.breaker: b for b in safety.circuits()}[CircuitBreakerType.RECONCILIATION_FAILURE]
    assert breaker.open is True
    with pytest.raises(SafetyHaltError):
        safety.require_new_entry_allowed(bot_id="demo-bot", symbol="BTC/USDT")


def test_audit_events_contain_reason_codes_not_resume_acknowledgement_text():
    store = MemorySafetyStore()
    safety = SafetyControlService(store)
    halt(safety, reason="manual_maintenance", idem="audit-halt-001")
    safety.resume(SafetyResumeRequest(idempotency_key="audit-resume-001", scope=SafetyScope.GLOBAL, operator_id="ops", acknowledgement="contains sensitive looking text"))

    serialized = " ".join(str(e.model_dump(mode="json")) for e in store.events)
    assert "manual_maintenance" in serialized
    assert "contains sensitive looking text" not in serialized
    assert "acknowledgement" in serialized
