from decimal import Decimal

from packages.exchange.demo import DemoOrderEngine
from packages.exchange.storage import DemoOrderStore
from packages.positions import PositionEngine, PositionStore
from packages.protection import ProtectionService, ProtectionStore
from packages.risk import RiskDecisionStore, RiskEngine, RiskEvaluationRequest
from packages.runtime import BotRuntime, RuntimeStore


class FilledDemoExchange:
    def __init__(self): self.calls = 0
    def submit(self, order):
        self.calls += 1
        return {"exchange_order_id": "filled-demo-1", "status": "filled", "filled_quantity": str(order.quantity), "fee": "1", "demo": True}


def test_complete_demo_flow_is_closed_candle_and_risk_guarded(db_session):
    db = db_session
    risk = RiskEngine(RiskDecisionStore(db)); positions = PositionEngine(PositionStore(db))
    protection = ProtectionService(positions.store, ProtectionStore(db))
    exchange = FilledDemoExchange()
    orders = DemoOrderEngine(risk.store, DemoOrderStore(db), exchange, on_filled=positions.apply_filled_order)
    runtime = BotRuntime(RuntimeStore(db), orders.order_store, positions, protection, risk, orders)
    request = RiskEvaluationRequest.model_validate({"proposal":{"symbol":"BTC/USDT","action":"BUY","price":"100","stop_price":"90"},"portfolio":{"available_balance":"1000"}})

    assert runtime.execute_closed_candle(request, Decimal("120"), Decimal("90"), candle_closed=False) is None
    decision, order, guarded = runtime.execute_closed_candle(request, Decimal("120"), Decimal("90"))
    assert decision.approved and order.status.value == "filled" and guarded.protection_status.value == "protected"
    assert positions.summary().open_positions == 1
    # Replaying exactly the same closed candle cannot bypass risk or submit a second exchange order.
    runtime.execute_closed_candle(request, Decimal("120"), Decimal("90"))
    assert exchange.calls == 1 and len(orders.order_store.list()) == 1
    runtime.recover(); assert any(event.event_type == "risk.decision" for event in runtime.store.events())



