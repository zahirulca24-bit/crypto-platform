from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from packages.research.models import ObservationCreate
from packages.research.service import ResearchObservationService


def test_observation_persistence(db_session):
    service = ResearchObservationService(db_session)
    created = service.record(ObservationCreate(
        event_type="market.snapshot", source="test", exchange="binance", symbol="BTC/USDT", timeframe="1m",
        price=Decimal("60000.12"), volume=Decimal("10.5"), spread=Decimal("0.02"),
        volatility=Decimal("0.015"), indicator_values={"rsi": 54.2},
    ))
    loaded = service.get(created.event_id)
    assert loaded is not None
    assert loaded.event_id == created.event_id
    assert loaded.price.quantize(Decimal("0.01")) == Decimal("60000.12")
    assert loaded.indicator_values == {"rsi": 54.2}


def test_selected_symbol_event(db_session):
    service = ResearchObservationService(db_session)
    event = service.record(ObservationCreate(
        event_type="symbol.selected", source="symbol_selection", exchange="binance", symbol="ETH/USDT",
        selection_score=Decimal("0.91"), selection_status="selected", selection_reasons=[],
        market_context={"selection_run_id": "run-1"},
    ))
    assert event.selection_status == "selected"
    assert event.selection_score == Decimal("0.910000000000")


def test_rejected_symbol_with_reason(db_session):
    service = ResearchObservationService(db_session)
    event = service.record(ObservationCreate(
        event_type="symbol.rejected", source="symbol_selection", exchange="binance", symbol="ABC/USDT",
        selection_status="rejected", selection_reasons=["spread_above_maximum"],
    ))
    assert event.selection_reasons == ["spread_above_maximum"]


def test_strategy_decision_context(db_session):
    service = ResearchObservationService(db_session)
    event = service.record(ObservationCreate(
        event_type="strategy.decision", source="strategy", exchange="binance", symbol="BTC/USDT", timeframe="5m",
        strategy_name="rsi_transition", strategy_version="1", strategy_config_hash="a" * 64,
        strategy_decision="BUY", strategy_reason="rsi_transition_up", indicator_values={"rsi": 31.2},
        decision_context={"proposal": {"action": "BUY"}},
    ))
    assert event.strategy_decision == "BUY"
    assert event.indicator_values["rsi"] == 31.2


def test_risk_rejection_context(db_session):
    service = ResearchObservationService(db_session)
    event = service.record(ObservationCreate(
        event_type="risk.rejected", source="risk_engine", symbol="BTC/USDT", side="BUY",
        risk_approved=False, risk_rejection_reasons=["MAX_OPEN_POSITIONS_REACHED"],
        decision_context={"policy_snapshot": {"max_open_positions": 10}},
    ))
    assert event.risk_approved is False
    assert event.risk_rejection_reasons == ["MAX_OPEN_POSITIONS_REACHED"]


def test_completed_trade_outcome_and_costs(db_session):
    service = ResearchObservationService(db_session)
    event = service.record(ObservationCreate(
        event_type="trade.completed", source="position_engine", exchange="demo", symbol="BTC/USDT", side="long",
        entry_price=Decimal("100"), exit_price=Decimal("110"), quantity=Decimal("2"), notional=Decimal("220"),
        take_profit=Decimal("115"), stop_loss=Decimal("95"), fees=Decimal("0.8"), slippage=Decimal("0.3"),
        realized_pnl=Decimal("20"), unrealized_pnl=Decimal("0"), holding_time_seconds=Decimal("3600"),
        exit_reason="take_profit", mae=Decimal("-3"), mfe=Decimal("12"),
    ))
    assert event.exit_reason == "take_profit"
    assert event.realized_pnl == Decimal("20.000000000000")
    assert event.fees == Decimal("0.800000000000")
    assert event.slippage == Decimal("0.300000000000")


def test_deterministic_retrieval_and_filtering(db_session):
    service = ResearchObservationService(db_session)
    base = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
    first = service.record(ObservationCreate(
        event_type="strategy.decision", source="test", symbol="BTC/USDT", strategy_name="s1", observed_at=base,
    ))
    second = service.record(ObservationCreate(
        event_type="strategy.decision", source="test", symbol="ETH/USDT", strategy_name="s1", observed_at=base + timedelta(seconds=1),
    ))
    service.record(ObservationCreate(
        event_type="risk.rejected", source="test", symbol="ETH/USDT", observed_at=base + timedelta(seconds=2),
    ))

    rows = service.list(event_type="strategy.decision", strategy="s1", start=base, end=base + timedelta(seconds=2))
    assert [row.event_id for row in rows] == [second.event_id, first.event_id]
    assert [row.symbol for row in service.list(symbol="eth/usdt")] == ["ETH/USDT", "ETH/USDT"]


def test_research_layer_cannot_trigger_order_execution(db_session, monkeypatch):
    from packages.exchange.demo import DemoOrderEngine

    called = False
    def forbidden_submit(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("research attempted order execution")

    monkeypatch.setattr(DemoOrderEngine, "submit", forbidden_submit)
    service = ResearchObservationService(db_session)
    service.record(ObservationCreate(event_type="test.observation", source="test"))

    assert called is False
    assert not hasattr(service, "submit")
    assert not hasattr(service, "execute_order")
