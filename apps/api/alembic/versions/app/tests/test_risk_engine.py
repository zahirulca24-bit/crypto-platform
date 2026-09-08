from decimal import Decimal

import pytest

from packages.risk import RiskDecisionStore, RiskEngine, RiskEvaluationRequest


def request(**overrides):
    body = {
        "proposal": {"symbol": "BTC/USDT", "action": "BUY", "price": "100", "stop_price": "90"},
        "portfolio": {"available_balance": "1000"},
        "policy": {
            "max_risk_per_trade": "100",
            "max_position_notional": "1000",
            "max_total_portfolio_exposure": "5000",
            "max_open_positions": 10,
            "max_exposure_per_symbol": "1000",
            "max_daily_loss": "500",
            "max_drawdown": "1000",
            "minimum_available_balance": "50",
            "minimum_trade_quantity": "0.00000001",
        },
    }
    for section, values in overrides.items():
        body[section].update(values)
    return RiskEvaluationRequest.model_validate(body)


@pytest.fixture
def engine(db_session):
    return RiskEngine(RiskDecisionStore(db_session / "risk.db"))


def test_valid_buy_approval(engine):
    decision = engine.evaluate(request())
    assert decision.approved is True
    assert decision.approved_quantity == Decimal("10")
    assert decision.approved_notional == Decimal("1000")
    assert decision.risk_amount == Decimal("100")


def test_valid_sell_approval(engine):
    decision = engine.evaluate(request(proposal={"symbol": "BTC/USDT", "action": "SELL", "price": "100", "stop_price": "110"}))
    assert decision.approved is True
    assert decision.approved_quantity == Decimal("10")


def test_risk_per_trade_rejection(engine):
    decision = engine.evaluate(request(proposal={"symbol": "BTC/USDT", "action": "BUY", "price": "100", "stop_price": "1"}, policy={"max_risk_per_trade": "1", "minimum_trade_quantity": "1"}))
    assert decision.approved is False
    assert "RISK_PER_TRADE_LIMIT" in decision.rejection_reasons


def test_max_position_rejection(engine):
    decision = engine.evaluate(request(portfolio={"available_balance": "1000", "positions": [{"symbol": "BTC/USDT", "quantity": "10", "mark_price": "100"}]}))
    assert decision.approved is False
    assert "MAX_POSITION_NOTIONAL" in decision.rejection_reasons


def test_total_exposure_rejection(engine):
    decision = engine.evaluate(request(proposal={"symbol": "ETH/USDT", "action": "BUY", "price": "100", "stop_price": "90"}, portfolio={"available_balance": "1000", "positions": [{"symbol": "BTC/USDT", "quantity": "50", "mark_price": "100"}]}, policy={"max_total_portfolio_exposure": "5000"}))
    assert decision.approved is False
    assert "MAX_TOTAL_PORTFOLIO_EXPOSURE" in decision.rejection_reasons


def test_max_open_positions_rejection(engine):
    decision = engine.evaluate(request(proposal={"symbol": "ETH/USDT", "action": "BUY", "price": "100", "stop_price": "90"}, portfolio={"available_balance": "1000", "positions": [{"symbol": "BTC/USDT", "quantity": "1", "mark_price": "100"}]}, policy={"max_open_positions": 1}))
    assert decision.approved is False
    assert "MAX_OPEN_POSITIONS_REACHED" in decision.rejection_reasons


def test_symbol_exposure_rejection(engine):
    decision = engine.evaluate(request(portfolio={"available_balance": "1000", "positions": [{"symbol": "BTC/USDT", "quantity": "5", "mark_price": "100"}]}, policy={"max_position_notional": "1000", "max_exposure_per_symbol": "500"}))
    assert decision.approved is False
    assert "MAX_SYMBOL_EXPOSURE" in decision.rejection_reasons


def test_reversal_cannot_bypass_position_limit(engine):
    decision = engine.evaluate(request(proposal={"symbol": "BTC/USDT", "action": "SELL", "price": "100", "stop_price": "110"}, portfolio={"available_balance": "1000", "positions": [{"symbol": "BTC/USDT", "quantity": "1", "mark_price": "100"}]}, policy={"max_position_notional": "100"}))
    assert decision.approved is True
    assert decision.approved_quantity == Decimal("2")  # closes +1 and opens only -1


def test_daily_loss_kill_rejection(engine):
    decision = engine.evaluate(request(portfolio={"available_balance": "1000", "daily_pnl": "-500"}))
    assert decision.approved is False
    assert "DAILY_LOSS_LIMIT_REACHED" in decision.rejection_reasons


def test_drawdown_rejection(engine):
    decision = engine.evaluate(request(portfolio={"available_balance": "1000", "peak_equity": "10000", "current_equity": "9000"}))
    assert decision.approved is False
    assert "DRAWDOWN_LIMIT_REACHED" in decision.rejection_reasons


def test_insufficient_balance_rejection(engine):
    decision = engine.evaluate(request(portfolio={"available_balance": "49"}))
    assert decision.approved is False
    assert "INSUFFICIENT_AVAILABLE_BALANCE" in decision.rejection_reasons


def test_invalid_price_rejection(engine):
    decision = engine.evaluate(request(proposal={"symbol": "BTC/USDT", "action": "BUY", "price": "0", "stop_price": "90"}))
    assert decision.approved is False
    assert "INVALID_PRICE" in decision.rejection_reasons


def test_sizing_is_deterministic(engine):
    first = engine.evaluate(request())
    second = engine.evaluate(request())
    assert first.approved_quantity == second.approved_quantity == Decimal("10")
    assert first.id == second.id


def test_decision_is_persisted(engine):
    saved = engine.evaluate(request())
    decisions = engine.store.list()
    assert [decision.id for decision in decisions] == [saved.id]


def test_duplicate_evaluation_creates_one_audit_decision(engine):
    engine.evaluate(request())
    engine.evaluate(request())
    assert len(engine.store.list()) == 1


