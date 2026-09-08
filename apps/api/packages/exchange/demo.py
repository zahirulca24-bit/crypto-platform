"""Demo-only exchange adapter and idempotent order submission service."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Callable, Protocol
from uuid import UUID

from packages.risk.models import RiskDecision
from packages.risk.storage import RiskDecisionStore

from .models import DemoOrder, DemoOrderSubmitRequest, OrderStatus
from .storage import DemoOrderStore


class DemoExchange(Protocol):
    def submit(self, order: DemoOrder) -> dict: ...


class DeterministicDemoExchange:
    """A local simulator: it never connects to a real venue or places a real order."""

    def submit(self, order: DemoOrder) -> dict:
        return {
            "exchange_order_id": f"demo-ex-{order.client_order_id}",
            "status": OrderStatus.OPEN.value,
            "filled_quantity": "0",
            "fee": "0",
            "demo": True,
        }


class ProductionTradingBlocked(RuntimeError):
    pass


class RiskDecisionNotApproved(RuntimeError):
    pass


class RiskDecisionNotFound(RuntimeError):
    pass


class DemoOrderEngine:
    def __init__(
        self,
        risk_store: RiskDecisionStore,
        order_store: DemoOrderStore,
        exchange: DemoExchange | None = None,
        trading_mode: str = "demo",
        on_filled: Callable[[DemoOrder], object] | None = None,
    ) -> None:
        self.risk_store = risk_store
        self.order_store = order_store
        self.exchange = exchange or DeterministicDemoExchange()
        self.trading_mode = trading_mode.lower()
        self.on_filled = on_filled

    @staticmethod
    def client_order_id_for(risk_decision_id: UUID) -> str:
        return "demo-" + hashlib.sha256(str(risk_decision_id).encode()).hexdigest()[:32]

    def submit(self, request: DemoOrderSubmitRequest) -> DemoOrder:
        if self.trading_mode != "demo":
            raise ProductionTradingBlocked("Only demo trading is enabled")

        # Returning the persisted record before touching the exchange makes retries safe.
        existing = self.order_store.get_by_risk_decision(request.risk_decision_id)
        if existing:
            if existing.status == OrderStatus.FILLED and self.on_filled:
                self.on_filled(existing)
            return existing
        decision = self.risk_store.get(str(request.risk_decision_id))
        if decision is None:
            raise RiskDecisionNotFound("Risk decision does not exist")
        if not decision.approved or decision.approved_quantity is None or decision.approved_notional is None:
            raise RiskDecisionNotApproved("Only an approved risk decision may create an order")

        order = DemoOrder(
            risk_decision_id=decision.id,
            client_order_id=self.client_order_id_for(decision.id),
            symbol=decision.proposal.symbol,
            side=decision.proposal.action.value,
            type=request.type,
            quantity=decision.approved_quantity,
            price=decision.proposal.price,
        )
        order, created = self.order_store.create(order)  # durable before any adapter interaction
        if not created:
            return order

        order.status = OrderStatus.SUBMITTING
        self.order_store.update(order)
        try:
            response = self.exchange.submit(order)
            order.exchange_order_id = response.get("exchange_order_id")
            order.filled_quantity = Decimal(str(response.get("filled_quantity", "0")))
            order.fee = Decimal(str(response.get("fee", "0")))
            order.status = OrderStatus(response.get("status", OrderStatus.UNKNOWN.value))
            order.raw_exchange_response = response
        except Exception as exc:
            # The request may or may not have reached an external system, so it is never retried automatically.
            order.status = OrderStatus.UNKNOWN
            order.raw_exchange_response = {"error": str(exc), "error_type": type(exc).__name__, "demo": True}
        order = self.order_store.update(order)
        if order.status == OrderStatus.FILLED and self.on_filled:
            self.on_filled(order)
        return order
