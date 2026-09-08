from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from database import Base
from models import (
    AppliedOrderFillModel, DemoOrderModel, MarketFeatureSnapshot, MarketRegimeSnapshot, OHLCVCandle,
    PositionModel, PositionProtectionModel, ResearchObservation, RiskDecisionModel, TradeOutcome,
)
from packages.exchange.models import DemoOrder, OrderStatus, OrderType
from packages.positions.models import Position, PositionSide, PositionStatus
from packages.protection.models import PositionProtection, ProtectionStatus
from packages.research.outcomes import OUTCOME_VERSION, OutcomeGenerateRequest, TradeOutcomeService
from packages.risk.models import OrderAction, RiskDecision, StrategyOrderProposal


@pytest.fixture
def outcome_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close(); engine.dispose()


def _seed_trade(db, *, entry=Decimal("100"), exit=Decimal("110"), qty=Decimal("2"), entry_fee=Decimal("1"),
                exit_fee=Decimal("1"), risk=Decimal("20"), tp=Decimal("110"), sl=Decimal("90"),
                slippage=Decimal("0.5"), strategy="alpha", regime="trending_bull", hour=0):
    t0 = datetime(2026, 9, 1, hour, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=2)
    pid = uuid4(); rid1=uuid4(); rid2=uuid4()
    pos = Position(id=pid, symbol="BTC/USDT", side=PositionSide.LONG, quantity=Decimal("0"),
                   average_entry_price=entry, current_price=exit, realized_pnl=(exit-entry)*qty,
                   fees=entry_fee+exit_fee, opened_at=t0, updated_at=t1, status=PositionStatus.CLOSED)
    db.add(PositionModel(id=pid, symbol=pos.symbol, status="closed", position_json=pos.model_dump(mode="json"), opened_at=t0, updated_at=t1))
    for rid, action, price, created, fee in [(rid1,OrderAction.BUY,entry,t0,entry_fee),(rid2,OrderAction.SELL,exit,t1,exit_fee)]:
        decision=RiskDecision(id=rid, proposal=StrategyOrderProposal(symbol="BTC/USDT",action=action,price=price,stop_price=sl),
                              approved=True,approved_quantity=qty,approved_notional=price*qty,risk_amount=risk,policy_snapshot={},created_at=created)
        db.add(RiskDecisionModel(id=rid,request_fingerprint=str(rid),decision_json=decision.model_dump(mode="json"),created_at=created))
        order=DemoOrder(risk_decision_id=rid,client_order_id=f"c-{rid}",symbol="BTC/USDT",side=action.value,type=OrderType.MARKET,
                        quantity=qty,price=price,filled_quantity=qty,fee=fee,status=OrderStatus.FILLED,created_at=created,updated_at=created)
        db.add(DemoOrderModel(id=order.id,risk_decision_id=rid,order_json=order.model_dump(mode="json"),created_at=created))
        db.add(AppliedOrderFillModel(order_id=order.id,position_id=pid,applied_at=created))
        if action == OrderAction.SELL:
            exit_order_id=order.id
    protection=PositionProtection(position_id=pid,tp_price=tp,sl_price=sl,protection_status=ProtectionStatus.PROTECTED)
    db.add(PositionProtectionModel(position_id=pid,protection_json=protection.model_dump(mode="json"),updated_at=t0))
    # Closed candles strictly inside trade; later candle is intentionally extreme and must never leak.
    candles=[]
    for idx,(at,lo,hi,close) in enumerate([(t0,Decimal("95"),Decimal("105"),Decimal("102")),(t0+timedelta(hours=1),Decimal("98"),Decimal("112"),Decimal("108")),(t1,Decimal("107"),Decimal("111"),exit)]):
        c=OHLCVCandle(exchange="demo",symbol="BTC/USDT",timeframe="1h",open_time=at,open=entry,high=hi,low=lo,close=close,volume=Decimal("1000"),is_closed=True)
        db.add(c); db.flush(); candles.append(c)
    future=OHLCVCandle(exchange="demo",symbol="BTC/USDT",timeframe="1h",open_time=t1+timedelta(hours=1),open=exit,high=Decimal("200"),low=Decimal("1"),close=exit,volume=Decimal("1000"),is_closed=True)
    db.add(future)
    fentry=MarketFeatureSnapshot(candle_id=candles[0].id,exchange="demo",symbol="BTC/USDT",timeframe="1h",candle_open_time=t0,feature_version="1.0.0",configuration={},configuration_hash=f"a{hour:063d}"[-64:])
    fexit=MarketFeatureSnapshot(candle_id=candles[-1].id,exchange="demo",symbol="BTC/USDT",timeframe="1h",candle_open_time=t1,feature_version="1.0.0",configuration={},configuration_hash=f"b{hour:063d}"[-64:])
    db.add_all([fentry,fexit]); db.flush()
    rentry=MarketRegimeSnapshot(feature_snapshot_id=fentry.id,exchange="demo",symbol="BTC/USDT",timeframe="1h",candle_open_time=t0,
        regime=regime,confidence_score=Decimal("0.8"),regime_version="1.0.0",configuration={},configuration_hash=f"c{hour:063d}"[-64:],supporting_signals={},reason="test",current_regime=regime,changed=False)
    rexit=MarketRegimeSnapshot(feature_snapshot_id=fexit.id,exchange="demo",symbol="BTC/USDT",timeframe="1h",candle_open_time=t1,
        regime=regime,confidence_score=Decimal("0.8"),regime_version="1.0.0",configuration={},configuration_hash=f"d{hour:063d}"[-64:],supporting_signals={},reason="test",current_regime=regime,changed=False)
    db.add_all([rentry,rexit])
    db.add(ResearchObservation(event_type="order.filled",source="test",exchange="demo",symbol="BTC/USDT",slippage=slippage,
                               trade_context={"order_id":str(exit_order_id)},observed_at=t1))
    db.commit()
    req=OutcomeGenerateRequest(position_id=pid,exchange="demo",timeframe="1h",strategy_name=strategy,strategy_version="2.0",strategy_config_hash="e"*64)
    return req, t0, t1


def test_winning_trade_and_calculations(outcome_db):
    req,_,_= _seed_trade(outcome_db)
    o=TradeOutcomeService(outcome_db).generate(req)
    assert o.gross_pnl==Decimal("20.000000000000")
    assert o.fees==Decimal("2.000000000000") and o.slippage==Decimal("0.500000000000")
    assert o.net_pnl==Decimal("17.500000000000") and o.return_pct==Decimal("10.000000000000")


def test_losing_trade(outcome_db):
    req,_,_= _seed_trade(outcome_db,exit=Decimal("90"),tp=Decimal("110"),sl=Decimal("90"))
    o=TradeOutcomeService(outcome_db).generate(req)
    assert o.gross_pnl < 0 and o.net_pnl < o.gross_pnl


def test_tp_exit(outcome_db):
    req,_,_= _seed_trade(outcome_db)
    assert TradeOutcomeService(outcome_db).generate(req).exit_reason=="take_profit"


def test_sl_exit(outcome_db):
    req,_,_= _seed_trade(outcome_db,exit=Decimal("90"))
    assert TradeOutcomeService(outcome_db).generate(req).exit_reason=="stop_loss"


def test_holding_time_mae_mfe_and_r_multiple(outcome_db):
    req,_,_= _seed_trade(outcome_db)
    o=TradeOutcomeService(outcome_db).generate(req)
    assert o.holding_time_seconds==Decimal("7200.000000")
    assert o.mae==Decimal("10.000000000000") and o.mfe==Decimal("24.000000000000")
    assert o.r_multiple==Decimal("0.875000000000")


def test_regime_and_feature_linkage(outcome_db):
    req,_,_= _seed_trade(outcome_db)
    o=TradeOutcomeService(outcome_db).generate(req)
    assert o.regime_at_entry=="trending_bull" and o.regime_at_exit=="trending_bull"
    assert o.entry_feature_snapshot_id and o.exit_feature_snapshot_id and o.entry_regime_snapshot_id and o.exit_regime_snapshot_id


def test_no_future_leakage_for_mae_mfe(outcome_db):
    req,_,_= _seed_trade(outcome_db)
    o=TradeOutcomeService(outcome_db).generate(req)
    assert o.mae==Decimal("10.000000000000") and o.mfe==Decimal("24.000000000000")
    assert o.context["mae_mfe_closed_candle_count"]==3


def test_deterministic_idempotent_generation(outcome_db):
    req,_,_= _seed_trade(outcome_db)
    service=TradeOutcomeService(outcome_db); a=service.generate(req); b=service.generate(req)
    assert a.id==b.id
    assert outcome_db.execute(select(func.count()).select_from(TradeOutcome)).scalar_one()==1


def _outcome(db, *, symbol="BTC/USDT", strategy="alpha", regime="ranging", net="10", gross=None, fees="1", slip="0", r="1", hour=0, exit_reason="strategy_exit"):
    t=datetime(2026,9,2,hour,tzinfo=timezone.utc); pid=uuid4()
    p=Position(id=pid,symbol=symbol,side=PositionSide.LONG,quantity=Decimal("0"),average_entry_price=Decimal("100"),current_price=Decimal("100"),opened_at=t,updated_at=t+timedelta(hours=1),status=PositionStatus.CLOSED)
    db.add(PositionModel(id=pid,symbol=symbol,status="closed",position_json=p.model_dump(mode="json"),opened_at=t,updated_at=t+timedelta(hours=1))); db.flush()
    n=Decimal(net); g=Decimal(gross if gross is not None else net)
    row=TradeOutcome(source_position_id=pid,exchange="demo",symbol=symbol,timeframe="1h",strategy_name=strategy,strategy_version="1",strategy_config_hash="unknown",side="long",
        entry_time=t,exit_time=t+timedelta(hours=1),entry_price=Decimal("100"),exit_price=Decimal("101"),quantity=Decimal("1"),notional=Decimal("100"),
        gross_pnl=g,net_pnl=n,fees=Decimal(fees),slippage=Decimal(slip),holding_time_seconds=Decimal("3600"),exit_reason=exit_reason,
        mae=Decimal("2"),mfe=Decimal("3"),return_pct=n,risk_amount=Decimal("10"),r_multiple=Decimal(r),regime_at_entry=regime,outcome_version=OUTCOME_VERSION,context={})
    db.add(row); db.commit(); return row


def test_performance_grouping_by_symbol(outcome_db):
    _outcome(outcome_db,symbol="BTC/USDT",net="10",hour=0); _outcome(outcome_db,symbol="ETH/USDT",net="5",hour=2)
    rows=TradeOutcomeService(outcome_db).performance(group_by="symbol")
    assert {x.group_value for x in rows}=={"BTC/USDT","ETH/USDT"}


def test_performance_grouping_by_strategy(outcome_db):
    _outcome(outcome_db,strategy="alpha",hour=0); _outcome(outcome_db,strategy="beta",hour=2)
    assert {x.group_value for x in TradeOutcomeService(outcome_db).performance(group_by="strategy")}=={"alpha","beta"}


def test_performance_grouping_by_regime(outcome_db):
    _outcome(outcome_db,regime="ranging",hour=0); _outcome(outcome_db,regime="breakout",hour=2)
    assert {x.group_value for x in TradeOutcomeService(outcome_db).performance(group_by="regime")}=={"ranging","breakout"}


def test_profit_factor_expectancy_and_drawdown(outcome_db):
    _outcome(outcome_db,net="10",hour=0,r="1"); _outcome(outcome_db,net="-5",hour=2,r="-.5"); _outcome(outcome_db,net="5",hour=4,r=".5")
    p=TradeOutcomeService(outcome_db).performance(group_by="strategy")[0]
    assert p.trade_count==3 and p.wins==2 and p.losses==1
    assert p.profit_factor==Decimal("3.000000000000")
    assert p.expectancy==Decimal("3.333333333333") and p.max_drawdown==Decimal("5.000000000000")


def test_history_filtering(outcome_db):
    a=_outcome(outcome_db,symbol="BTC/USDT",strategy="alpha",regime="ranging",hour=0,exit_reason="manual")
    _outcome(outcome_db,symbol="ETH/USDT",strategy="beta",regime="breakout",hour=2)
    rows=TradeOutcomeService(outcome_db).list(symbol="btc/usdt",strategy="alpha",regime="ranging",timeframe="1h",exit_reason="manual")
    assert [x.id for x in rows]==[a.id]


def test_research_observation_linkage(outcome_db):
    req,_,_= _seed_trade(outcome_db)
    o=TradeOutcomeService(outcome_db).generate(req)
    obs=outcome_db.get(ResearchObservation,o.observation_event_id)
    assert obs.event_type=="trade_outcome" and obs.realized_pnl==o.net_pnl
    assert obs.trade_context["regime_at_entry"]=="trending_bull" and obs.trade_context["r_multiple"]=="0.875000000000"


def test_open_position_rejected(outcome_db):
    t=datetime(2026,9,1,tzinfo=timezone.utc); p=Position(symbol="BTC/USDT",side=PositionSide.LONG,quantity=Decimal("1"),average_entry_price=Decimal("100"),current_price=Decimal("100"),opened_at=t,updated_at=t,status=PositionStatus.OPEN)
    outcome_db.add(PositionModel(id=p.id,symbol=p.symbol,status="open",position_json=p.model_dump(mode="json"),opened_at=t,updated_at=t)); outcome_db.commit()
    with pytest.raises(ValueError): TradeOutcomeService(outcome_db).generate(OutcomeGenerateRequest(position_id=p.id,strategy_name="alpha"))


def test_research_outcome_engine_cannot_trigger_trading_actions():
    names=set(dir(TradeOutcomeService)); forbidden={"place_order","submit_order","execute_order","approve_risk","open_position","close_position","decrypt_credentials","start_bot","modify_order"}
    assert names.isdisjoint(forbidden)
    import inspect, packages.research.outcomes as module
    source=inspect.getsource(module)
    assert "packages.exchange.adapter" not in source and "ccxt" not in source and "decrypt" not in source


def test_outcome_version():
    assert OUTCOME_VERSION=="1.0.0"
