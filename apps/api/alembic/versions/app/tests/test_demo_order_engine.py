from decimal import Decimal

import pytest

from packages.exchange.demo import DemoOrderEngine, ProductionTradingBlocked, RiskDecisionNotApproved
from packages.exchange.models import DemoOrderSubmitRequest, OrderStatus
from packages.exchange.storage import DemoOrderStore
from packages.risk import RiskDecisionStore, RiskEngine, RiskEvaluationRequest


def approved_request():
    return RiskEvaluationRequest.model_validate({
        "proposal": {"symbol": "BTC/USDT", "action": "BUY", "price": "100", "stop_price": "90"},
        "portfolio": {"available_balance": "1000"},
    })


@pytest.fixture
def services(db_session):
    risk_store = RiskDecisionStore(db_session / "orders.db")
    decision = RiskEngine(risk_store).evaluate(approved_request())
    return decision, risk_store, DemoOrderStore(db_session / "orders.db")


def test_approved_order_is_submitted(services):
    decision, risk_store, order_store = services
    order = DemoOrderEngine(risk_store, order_store).submit(DemoOrderSubmitRequest(risk_decision_id=decision.id))
    assert order.status == OrderStatus.OPEN
    assert order.quantity == Decimal("10")
    assert order.exchange_order_id
    assert order.raw_exchange_response["demo"] is True


def test_rejected_risk_decision_is_blocked(db_session):
    risk_store = RiskDecisionStore(db_session / "orders.db")
    rejected = RiskEngine(risk_store).evaluate(RiskEvaluationRequest.model_validate({
        "proposal": {"symbol": "BTC/USDT", "action": "BUY", "price": "0", "stop_price": "90"},
        "portfolio": {"available_balance": "1000"},
    }))
    with pytest.raises(RiskDecisionNotApproved):
        DemoOrderEngine(risk_store, DemoOrderStore(db_session / "orders.db")).submit(DemoOrderSubmitRequest(risk_decision_id=rejected.id))


def test_duplicate_submission_returns_same_order_and_calls_exchange_once(services):
    class CountingExchange:
        calls = 0
        def submit(self, order):
            self.calls += 1
            return {"exchange_order_id": "once", "status": "open", "filled_quantity": "0"}

    decision, risk_store, order_store = services
    exchange = CountingExchange()
    engine = DemoOrderEngine(risk_store, order_store, exchange)
    first = engine.submit(DemoOrderSubmitRequest(risk_decision_id=decision.id))
    second = engine.submit(DemoOrderSubmitRequest(risk_decision_id=decision.id))
    assert first.id == second.id
    assert exchange.calls == 1
    assert len(order_store.list()) == 1


def test_client_order_id_is_deterministic(services):
    decision, risk_store, order_store = services
    assert DemoOrderEngine.client_order_id_for(decision.id) == DemoOrderEngine.client_order_id_for(decision.id)
    order = DemoOrderEngine(risk_store, order_store).submit(DemoOrderSubmitRequest(risk_decision_id=decision.id))
    assert order.client_order_id == DemoOrderEngine.client_order_id_for(decision.id)


def test_production_mode_is_blocked(services):
    decision, risk_store, order_store = services
    with pytest.raises(ProductionTradingBlocked):
        DemoOrderEngine(risk_store, order_store, trading_mode="production").submit(DemoOrderSubmitRequest(risk_decision_id=decision.id))
    assert order_store.list() == []


def test_exchange_error_is_persisted_as_unknown(services):
    class FailingExchange:
        def submit(self, order):
            raise ConnectionError("demo adapter unavailable")

    decision, risk_store, order_store = services
    order = DemoOrderEngine(risk_store, order_store, FailingExchange()).submit(DemoOrderSubmitRequest(risk_decision_id=decision.id))
    assert order.status == OrderStatus.UNKNOWN
    assert order.raw_exchange_response["error_type"] == "ConnectionError"
    assert order_store.get(order.id).status == OrderStatus.UNKNOWN


