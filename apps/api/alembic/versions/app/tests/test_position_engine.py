from decimal import Decimal

import pytest

from packages.exchange.models import DemoOrder, OrderStatus, OrderType
from packages.positions import PositionEngine, PositionSide, PositionStatus, PositionStore


def fill(symbol="BTC/USDT", side="BUY", quantity="2", price="100", fee="1"):
    return DemoOrder(symbol=symbol, side=side, type=OrderType.LIMIT, quantity=Decimal(quantity), price=Decimal(price), filled_quantity=Decimal(quantity), fee=Decimal(fee), status=OrderStatus.FILLED, risk_decision_id="00000000-0000-0000-0000-000000000001", client_order_id=f"test-{side}-{quantity}-{price}")


@pytest.fixture
def engine(db_session):
    return PositionEngine(PositionStore(db_session / "positions.db"))


def test_open_position(engine):
    position = engine.apply_filled_order(fill())
    assert position.side == PositionSide.LONG
    assert position.quantity == Decimal("2")
    assert position.average_entry_price == Decimal("100")
    assert position.fees == Decimal("1")


def test_increase_position_uses_weighted_average(engine):
    engine.apply_filled_order(fill(quantity="2", price="100"))
    position = engine.apply_filled_order(fill(quantity="2", price="110"))
    assert position.quantity == Decimal("4")
    assert position.average_entry_price == Decimal("105")
    assert position.unrealized_pnl == Decimal("20")


def test_partial_close_realizes_pnl(engine):
    engine.apply_filled_order(fill(quantity="4", price="100"))
    position = engine.apply_filled_order(fill(side="SELL", quantity="1", price="120"))
    assert position.quantity == Decimal("3")
    assert position.realized_pnl == Decimal("20")
    assert position.unrealized_pnl == Decimal("60")


def test_full_close(engine):
    engine.apply_filled_order(fill(quantity="2", price="100"))
    position = engine.apply_filled_order(fill(side="SELL", quantity="2", price="110"))
    assert position.status == PositionStatus.CLOSED
    assert position.quantity == Decimal("0")
    assert position.realized_pnl == Decimal("20")


def test_opposite_side_fill_closes_and_reopens_safely(engine):
    engine.apply_filled_order(fill(quantity="2", price="100"))
    position = engine.apply_filled_order(fill(side="SELL", quantity="3", price="110"))
    assert position.side == PositionSide.SHORT
    assert position.quantity == Decimal("1")
    assert position.average_entry_price == Decimal("110")
    assert position.realized_pnl == Decimal("20")


def test_portfolio_pnl_calculation(engine):
    engine.apply_filled_order(fill(quantity="2", price="100", fee="1"))
    engine.apply_filled_order(fill(side="SELL", quantity="1", price="110", fee="2"))
    summary = engine.summary()
    assert summary.realized_pnl == Decimal("10")
    assert summary.unrealized_pnl == Decimal("10")
    assert summary.fees == Decimal("3")
    assert summary.net_pnl == Decimal("17")


def test_duplicate_fill_is_idempotent(engine):
    order = fill()
    first = engine.apply_filled_order(order)
    second = engine.apply_filled_order(order)
    assert first.id == second.id
    assert second.quantity == Decimal("2")


