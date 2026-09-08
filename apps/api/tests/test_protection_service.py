from decimal import Decimal

from packages.exchange.models import DemoOrder, OrderStatus, OrderType
from packages.positions import PositionEngine, PositionStatus, PositionStore
from packages.protection import DemoProtectionExchange, ProtectionRequest, ProtectionService, ProtectionStatus, ProtectionStore


def filled_order():
    return DemoOrder(
        risk_decision_id="00000000-0000-0000-0000-000000000001", client_order_id="filled-order", symbol="BTC/USDT", side="BUY", type=OrderType.LIMIT,
        quantity=Decimal("1"), price=Decimal("100"), filled_quantity=Decimal("1"), status=OrderStatus.FILLED,
    )


def setup(db_session):
    position_store = PositionStore(db_session)
    position = PositionEngine(position_store).apply_filled_order(filled_order())
    exchange = DemoProtectionExchange()
    service = ProtectionService(position_store, ProtectionStore(db_session), exchange)
    return position, service, exchange


def request(position):
    return ProtectionRequest(position_id=position.id, tp_price=Decimal("120"), sl_price=Decimal("90"))


def test_create_protection(db_session):
    position, service, _ = setup(db_session)
    protection = service.ensure(request(position))
    assert protection.protection_status == ProtectionStatus.PROTECTED
    assert protection.tp_order_id and protection.sl_order_id


def test_duplicate_creation_is_idempotent(db_session):
    position, service, exchange = setup(db_session)
    first = service.ensure(request(position))
    second = service.ensure(request(position))
    assert first.tp_order_id == second.tp_order_id
    assert len(exchange.order_ids) == 2


def test_missing_protection_is_detected(db_session):
    position, service, exchange = setup(db_session)
    protection = service.ensure(request(position))
    exchange.order_ids.remove(protection.sl_order_id)
    detected = service.detect_missing(position.id)
    assert detected.protection_status == ProtectionStatus.MISSING


def test_reconciliation_restores_missing_protection(db_session):
    position, service, exchange = setup(db_session)
    protection = service.ensure(request(position))
    exchange.order_ids.clear()  # models an adapter restart/reconciliation where both legs are absent
    recovered = service.reconcile()
    assert recovered[0].protection_status == ProtectionStatus.PROTECTED
    assert len(exchange.order_ids) == 2


def test_closed_position_gets_no_new_protection(db_session):
    position, service, exchange = setup(db_session)
    position.status = PositionStatus.CLOSED
    service.position_store.save(position)
    protection = service.ensure(request(position))
    assert protection.protection_status == ProtectionStatus.NOT_REQUIRED
    assert not exchange.order_ids



