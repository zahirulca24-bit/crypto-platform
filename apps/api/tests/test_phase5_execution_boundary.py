from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from packages.exchange.demo import DemoOrderEngine
from packages.exchange.execution import (
    AccountCapabilities,
    ExecutionAdapter,
    ExecutionGateway,
    ExecutionMode,
    ExecutionResult,
    LiveExecutionNotAllowedError,
    SafeToRetrySubmissionError,
    UnknownOrderStateError,
)
from packages.exchange.models import DemoOrder, DemoOrderSubmitRequest, OrderStatus
from packages.risk.models import OrderAction, RiskDecision, StrategyOrderProposal
from services.system_capabilities import CapabilitiesService
from settings import AppSettings, RuntimeMode, TradingMode


class MemoryRiskStore:
    def __init__(self, decision: RiskDecision):
        self.decision = decision

    def get(self, decision_id: str):
        return self.decision if str(self.decision.id) == str(decision_id) else None


class MemoryOrderStore:
    def __init__(self):
        self.by_id = {}
        self.by_risk = {}

    def get(self, order_id):
        return self.by_id.get(str(order_id))

    def get_by_risk_decision(self, risk_decision_id):
        return self.by_risk.get(str(risk_decision_id))

    def create(self, order):
        existing = self.get_by_risk_decision(order.risk_decision_id)
        if existing:
            return existing, False
        self.by_id[str(order.id)] = order.model_copy(deep=True)
        self.by_risk[str(order.risk_decision_id)] = self.by_id[str(order.id)]
        return self.by_id[str(order.id)], True

    def update(self, order):
        saved = order.model_copy(deep=True)
        self.by_id[str(order.id)] = saved
        self.by_risk[str(order.risk_decision_id)] = saved
        return saved

    def list(self, limit=100, offset=0):
        return list(self.by_id.values())[offset:offset + limit]


class RecordingAdapter:
    def __init__(self, mode=ExecutionMode.DEMO, behavior="success"):
        self.mode = mode
        self.behavior = behavior
        self.submit_calls = 0
        self.validate_calls = 0
        self.reconcile_calls = 0

    def validate_account_capabilities(self):
        self.validate_calls += 1
        return AccountCapabilities(authenticated=True, can_trade=True, supports_client_order_id=True)

    def submit_order(self, order):
        self.submit_calls += 1
        if self.behavior == "unknown":
            raise UnknownOrderStateError("ambiguous")
        if self.behavior == "safe_retry_once" and self.submit_calls == 1:
            raise SafeToRetrySubmissionError("not transmitted")
        return ExecutionResult(
            exchange_order_id="ex-1",
            status=OrderStatus.OPEN,
            raw={"status": "open", "client_order_id": order.client_order_id},
        )

    def find_order_by_client_id(self, client_order_id, symbol):
        self.reconcile_calls += 1
        return None


def approved_decision():
    proposal = StrategyOrderProposal(
        symbol="BTC/USDT",
        action=OrderAction.BUY,
        price=Decimal("100"),
        stop_price=Decimal("90"),
    )
    return RiskDecision(
        proposal=proposal,
        approved=True,
        approved_quantity=Decimal("1"),
        approved_notional=Decimal("100"),
        risk_amount=Decimal("10"),
        policy_snapshot={},
    )


def make_engine(adapter, *, trading_mode="demo", runtime_mode="development", allow_live=False):
    decision = approved_decision()
    store = MemoryOrderStore()
    gateway = ExecutionGateway(
        adapter,
        mode=adapter.mode,
        runtime_mode=runtime_mode,
        allow_live_trading=allow_live,
        retry_delay_seconds=0,
    )
    engine = DemoOrderEngine(
        MemoryRiskStore(decision),
        store,
        trading_mode=trading_mode,
        gateway=gateway,
        runtime_mode=runtime_mode,
        allow_live_trading=allow_live,
    )
    return decision, store, engine


def test_duplicate_submission_is_blocked_before_gateway_second_call():
    adapter = RecordingAdapter()
    decision, store, engine = make_engine(adapter)
    request = DemoOrderSubmitRequest(risk_decision_id=decision.id)
    first = engine.submit(request)
    second = engine.submit(request)
    assert first.id == second.id
    assert adapter.submit_calls == 1
    assert len(store.list()) == 1
    assert first.client_order_id == engine.client_order_id_for(decision.id)


def test_unknown_submission_state_is_not_retried_and_forces_reconciliation():
    adapter = RecordingAdapter(behavior="unknown")
    decision, _, engine = make_engine(adapter)
    request = DemoOrderSubmitRequest(risk_decision_id=decision.id)
    first = engine.submit(request)
    second = engine.submit(request)
    assert first.status is OrderStatus.UNKNOWN
    assert first.reconciliation_required is True
    assert first.execution_error_code == "unknown_order_state"
    assert second.id == first.id
    assert adapter.submit_calls == 1


def test_only_explicit_not_transmitted_failure_may_retry_submission():
    adapter = RecordingAdapter(behavior="safe_retry_once")
    decision, _, engine = make_engine(adapter)
    order = engine.submit(DemoOrderSubmitRequest(risk_decision_id=decision.id))
    assert order.status is OrderStatus.OPEN
    assert adapter.submit_calls == 2


def test_demo_and_live_gateway_routing_are_explicit():
    demo = RecordingAdapter(mode=ExecutionMode.DEMO)
    live = RecordingAdapter(mode=ExecutionMode.LIVE)
    ExecutionGateway(demo, mode="demo")
    ExecutionGateway(live, mode="live", runtime_mode="production", allow_live_trading=True)
    with pytest.raises(ValueError):
        ExecutionGateway(demo, mode="live", runtime_mode="production", allow_live_trading=True)


def test_live_disabled_state_rejects_before_adapter_account_or_submit_calls():
    adapter = RecordingAdapter(mode=ExecutionMode.LIVE)
    decision, _, engine = make_engine(adapter, trading_mode="live", runtime_mode="production", allow_live=False)
    order = engine.submit(DemoOrderSubmitRequest(risk_decision_id=decision.id))
    assert order.status is OrderStatus.REJECTED
    assert order.execution_error_code == "live_execution_not_allowed"
    assert adapter.validate_calls == 0
    assert adapter.submit_calls == 0


def test_live_requires_account_capability_validation_before_submission():
    adapter = RecordingAdapter(mode=ExecutionMode.LIVE)
    decision, _, engine = make_engine(adapter, trading_mode="live", runtime_mode="production", allow_live=True)
    order = engine.submit(DemoOrderSubmitRequest(risk_decision_id=decision.id))
    assert order.status is OrderStatus.OPEN
    assert adapter.validate_calls == 1
    assert adapter.submit_calls == 1


def test_live_configuration_is_fail_closed_and_capability_reflects_gate():
    blocked = AppSettings(runtime_mode=RuntimeMode.PRODUCTION, trading_mode=TradingMode.LIVE)
    codes = {reason.code for reason in blocked.validation_reasons()}
    assert "live_trading_not_explicitly_enabled" in codes
    assert "live_exchange_required" in codes

    allowed = AppSettings(
        runtime_mode=RuntimeMode.PRODUCTION,
        trading_mode=TradingMode.LIVE,
        allow_live_trading=True,
        live_exchange_id="kraken",
        database_url="postgresql://app:strong@db.internal:5432/crypto",
        redis_url="rediss://cache.internal:6379/0",
        jwt_secret_key="production-secret-material-at-least-32-characters",
        cors_allow_origins=("https://crypto.example",),
    )
    assert allowed.validation_reasons() == []
    assert CapabilitiesService(allowed).capabilities().capabilities["live_order_execution"].enabled is True


def test_strategy_research_routers_and_frontend_do_not_instantiate_ccxt():
    repo = Path(__file__).resolve().parents[3]
    roots = [
        repo / "apps/api/strategies.py",
        repo / "apps/api/services/strategy.py",
        repo / "apps/api/packages/research",
        repo / "apps/api/routers",
        repo / "apps/web",
    ]
    forbidden = ("import ccxt", "from ccxt", "ccxt.")
    offenders = []
    for root in roots:
        files = [root] if root.is_file() else list(root.rglob("*.py")) + list(root.rglob("*.ts")) + list(root.rglob("*.tsx")) + list(root.rglob("*.js")) + list(root.rglob("*.jsx"))
        for path in files:
            text = path.read_text(errors="ignore")
            if any(token in text for token in forbidden):
                offenders.append(str(path.relative_to(repo)))
    assert offenders == []


def test_private_execution_credentials_are_confined_to_approved_adapter_source():
    repo = Path(__file__).resolve().parents[3]
    api = repo / "apps/api"
    credential_tokens = ("LIVE_API_KEY", "LIVE_API_SECRET", "LIVE_API_PASSWORD", "DEMO_API_KEY", "DEMO_API_SECRET", "DEMO_API_PASSWORD")
    offenders = []
    for path in api.rglob("*.py"):
        if "tests" in path.parts or "alembic" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        allowed = {"exchange/execution_adapter.py", "exchange/demo_adapter.py"}
        rel = str(path.relative_to(api))
        if any(token in text for token in credential_tokens) and rel not in allowed:
            offenders.append(str(path.relative_to(repo)))
    assert offenders == []


def test_execution_errors_and_capability_api_do_not_expose_credentials(caplog):
    secret = "SUPER-SECRET-EXECUTION-CREDENTIAL"
    adapter = RecordingAdapter(mode=ExecutionMode.LIVE, behavior="unknown")
    decision, _, engine = make_engine(adapter, trading_mode="live", runtime_mode="production", allow_live=True)
    order = engine.submit(DemoOrderSubmitRequest(risk_decision_id=decision.id))
    assert secret not in str(order.model_dump())
    assert order.raw_exchange_response == {"error_code": "unknown_order_state"}

    settings = AppSettings(live_exchange_id="kraken")
    serialized = CapabilitiesService(settings).capabilities().model_dump_json()
    assert secret not in serialized
    assert "api_key" not in serialized.lower()
    assert "api_secret" not in serialized.lower()


def test_execution_boundary_exposes_no_withdrawal_api():
    from packages.exchange import execution
    adapter_contract = inspect.getsource(execution.ExecutionAdapter)
    gateway_contract = inspect.getsource(execution.ExecutionGateway)
    assert "withdraw" not in adapter_contract.lower()
    assert "withdraw" not in gateway_contract.lower()
