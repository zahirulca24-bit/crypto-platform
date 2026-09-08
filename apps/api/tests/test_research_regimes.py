from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from database import Base
from models import MarketFeatureSnapshot, MarketRegimeSnapshot, OHLCVCandle, ResearchObservation
from packages.research.regimes import (
    DEFAULT_REGIME_CONFIG, REGIME_VERSION, MarketRegimeService, RegimeClassifyRequest,
    canonical_regime_configuration_hash,
)


@pytest.fixture
def regime_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try: yield db
    finally:
        db.close(); engine.dispose()


def _feature(db, hour=0, **kw):
    at = datetime(2026, 9, 1) + timedelta(hours=hour)
    candle = OHLCVCandle(exchange="binance", symbol="BTC/USDT", timeframe="1h", open_time=at,
        open=Decimal("100"), high=Decimal("102"), low=Decimal("98"), close=Decimal("101"), volume=Decimal("1000"), is_closed=True)
    db.add(candle); db.flush()
    base = dict(
        candle_id=candle.id, exchange="binance", symbol="BTC/USDT", timeframe="1h", candle_open_time=at,
        feature_version="1.0.0", configuration={}, configuration_hash=f"f{hour:063d}"[-64:],
        volatility=Decimal("0.010"), atr=Decimal("2"), moving_average_distance=Decimal("0"),
        moving_average_slope=Decimal("0"), price_vs_sma_fast=Decimal("0"), price_vs_sma_slow=Decimal("0"),
        price_vs_ema_fast=Decimal("0"), price_vs_ema_slow=Decimal("0"), rsi=Decimal("50"),
        macd=Decimal("0"), macd_signal=Decimal("0"), macd_histogram=Decimal("0"), momentum=Decimal("0"),
        range_percentile=Decimal("0.5"), rolling_high_distance=Decimal("0.03"), rolling_low_distance=Decimal("0.03"),
        activity=Decimal("0.5"), spread_quality=Decimal("0.8"), liquidity=Decimal("0.8"), rolling_return=Decimal("0"), return_1=Decimal("0"),
    )
    base.update(kw)
    row = MarketFeatureSnapshot(**base); db.add(row); db.commit(); return row


def _classify(db, row, config=None):
    return MarketRegimeService(db).classify(RegimeClassifyRequest(feature_snapshot_id=row.id, configuration=config))


def test_bullish_trend_classification(regime_db):
    f=_feature(regime_db, moving_average_distance=Decimal(".01"), moving_average_slope=Decimal(".005"), momentum=Decimal(".02"), macd_histogram=Decimal(".5"), price_vs_sma_slow=Decimal(".02"))
    r=_classify(regime_db,f); assert r.regime=="trending_bull" and float(r.confidence_score)>=.8


def test_bearish_trend_classification(regime_db):
    f=_feature(regime_db, moving_average_distance=Decimal("-.01"), moving_average_slope=Decimal("-.005"), momentum=Decimal("-.02"), macd_histogram=Decimal("-.5"), price_vs_sma_slow=Decimal("-.02"))
    assert _classify(regime_db,f).regime=="trending_bear"


def test_ranging_classification(regime_db):
    assert _classify(regime_db,_feature(regime_db)).regime=="ranging"


def test_high_volatility_classification(regime_db):
    assert _classify(regime_db,_feature(regime_db, volatility=Decimal(".04"))).regime=="high_volatility"


def test_low_volatility_classification(regime_db):
    assert _classify(regime_db,_feature(regime_db, volatility=Decimal(".001"))).regime=="low_volatility"


def test_breakout_classification(regime_db):
    f=_feature(regime_db, range_percentile=Decimal(".99"), rolling_high_distance=Decimal(".001"), activity=Decimal(".95"))
    assert _classify(regime_db,f).regime=="breakout"


def test_mean_reverting_classification(regime_db):
    f=_feature(regime_db, rsi=Decimal("20"), price_vs_sma_slow=Decimal("-.03"), moving_average_distance=Decimal(".004"), moving_average_slope=Decimal(".002"), momentum=Decimal("0"))
    assert _classify(regime_db,f).regime=="mean_reverting"


def test_unknown_insufficient_data(regime_db):
    f=_feature(regime_db, volatility=None, atr=None, moving_average_distance=None, moving_average_slope=None,
        price_vs_sma_fast=None, price_vs_sma_slow=None, price_vs_ema_fast=None, price_vs_ema_slow=None, rsi=None,
        macd=None, macd_signal=None, macd_histogram=None, momentum=None, range_percentile=None, rolling_high_distance=None,
        rolling_low_distance=None, activity=None, spread_quality=None, liquidity=None, rolling_return=None, return_1=None)
    r=_classify(regime_db,f); assert r.regime=="unknown" and float(r.confidence_score)==0


def test_deterministic_confidence_and_idempotency(regime_db):
    f=_feature(regime_db, moving_average_distance=Decimal(".01"), moving_average_slope=Decimal(".005"), momentum=Decimal(".02"), macd_histogram=Decimal(".5"), price_vs_sma_slow=Decimal(".02"))
    a=_classify(regime_db,f); b=_classify(regime_db,f)
    assert a.id==b.id and a.confidence_score==b.confidence_score
    assert regime_db.execute(select(func.count()).select_from(MarketRegimeSnapshot)).scalar_one()==1


def test_no_future_leakage(regime_db):
    early=_feature(regime_db, hour=1)
    later=_feature(regime_db, hour=2, volatility=Decimal(".08"))
    _classify(regime_db,later)
    result=_classify(regime_db,early)
    assert result.regime=="ranging" and result.previous_regime is None


def test_regime_transition_detection(regime_db):
    first=_feature(regime_db,hour=1)
    second=_feature(regime_db,hour=2, volatility=Decimal(".04"))
    a=_classify(regime_db,first); b=_classify(regime_db,second)
    assert a.regime=="ranging"; assert b.previous_regime=="ranging" and b.current_regime=="high_volatility" and b.changed is True
    assert "ranging" in b.transition_reason


def test_current_regime_retrieval(regime_db):
    a=_feature(regime_db,hour=1); b=_feature(regime_db,hour=2, volatility=Decimal(".04"))
    _classify(regime_db,a); latest=_classify(regime_db,b)
    current=MarketRegimeService(regime_db).current(symbol="btc/usdt", timeframe="1h", exchange="BINANCE")
    assert current.id==latest.id


def test_history_filtering(regime_db):
    a=_feature(regime_db,hour=1); b=_feature(regime_db,hour=2, volatility=Decimal(".04"))
    _classify(regime_db,a); high=_classify(regime_db,b)
    rows=MarketRegimeService(regime_db).list(symbol="BTC/USDT", timeframe="1h", regime="high_volatility", start=b.candle_open_time)
    assert [x.id for x in rows]==[high.id]


def test_research_observation_linkage(regime_db):
    r=_classify(regime_db,_feature(regime_db))
    assert r.observation_event_id is not None
    obs=regime_db.get(ResearchObservation,r.observation_event_id)
    assert obs.event_type=="market_regime" and obs.context["regime_snapshot_id"]==str(r.id)
    assert obs.decision_context["transition"]["current_regime"]==r.regime


def test_canonical_configuration_hash():
    a={"b":2,"a":1,"nested": {"z":3,"x":4}}; b={"nested":{"x":4,"z":3},"a":1,"b":2}
    assert canonical_regime_configuration_hash(a)==canonical_regime_configuration_hash(b)
    assert len(canonical_regime_configuration_hash(DEFAULT_REGIME_CONFIG))==64


def test_research_regime_engine_cannot_trigger_trading_actions():
    service_names=set(dir(MarketRegimeService))
    forbidden={"place_order","submit_order","execute_order","approve_risk","open_position","close_position","decrypt_credentials","start_bot"}
    assert service_names.isdisjoint(forbidden)
    source=__import__("inspect").getsource(__import__("packages.research.regimes",fromlist=["*"]))
    assert "packages.exchange" not in source and "packages.risk" not in source and "ccxt" not in source


def test_regime_version():
    assert REGIME_VERSION=="1.0.0"
