from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from database import Base
from models import (
    MarketFeatureSnapshot,
    OHLCVCandle,
    ResearchObservation,
    SymbolSelectionResult,
    SymbolSelectionRun,
)
from packages.research.features import (
    DEFAULT_FEATURE_CONFIG,
    FEATURE_VERSION,
    FeatureGenerateRequest,
    MarketFeatureService,
    canonical_configuration_hash,
)


@pytest.fixture
def feature_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed_candles(db, count=60, *, symbol="BTC/USDT", closed=True, future_spike=False):
    start = datetime(2026, 1, 1)
    rows = []
    for i in range(count):
        close = Decimal(str(100 + i + (2 if i % 3 == 0 else 0)))
        open_ = close - Decimal("1")
        row = OHLCVCandle(
            exchange="binance", symbol=symbol, timeframe="1h",
            open_time=start + timedelta(hours=i), open=open_, high=close + Decimal("2"),
            low=open_ - Decimal("2"), close=close, volume=Decimal(str(1000 + i * 10)),
            is_closed=closed,
        )
        db.add(row)
        rows.append(row)
    if future_spike:
        db.add(OHLCVCandle(
            exchange="binance", symbol=symbol, timeframe="1h",
            open_time=start + timedelta(hours=count), open=Decimal("9999"), high=Decimal("12000"),
            low=Decimal("9000"), close=Decimal("11000"), volume=Decimal("999999"), is_closed=True,
        ))
    db.commit()
    return rows


def _request(row, configuration=None):
    return FeatureGenerateRequest(
        exchange=row.exchange, symbol=row.symbol, timeframe=row.timeframe,
        candle_open_time=row.open_time, configuration=configuration,
    )


def test_closed_candle_only_generation(feature_db):
    rows = _seed_candles(feature_db, 40)
    rows[-1].is_closed = False
    feature_db.commit()
    with pytest.raises(LookupError, match="Closed candle not found"):
        MarketFeatureService(feature_db).generate(_request(rows[-1]))


def test_deterministic_feature_output_and_version(feature_db):
    rows = _seed_candles(feature_db, 50)
    service = MarketFeatureService(feature_db)
    first = service.generate(_request(rows[-1]))
    second = service.generate(_request(rows[-1]))
    assert first.id == second.id
    assert first.features == second.features
    assert first.feature_version == FEATURE_VERSION == "1.0.0"


def test_no_future_leakage(feature_db):
    rows = _seed_candles(feature_db, 40, future_spike=True)
    target = rows[-1]
    snapshot = MarketFeatureService(feature_db).generate(_request(target))
    closes = [float(row.close) for row in rows]
    expected_fast = sum(closes[-DEFAULT_FEATURE_CONFIG["sma_fast"]:]) / DEFAULT_FEATURE_CONFIG["sma_fast"]
    assert float(snapshot.features["sma_fast"]) == pytest.approx(expected_fast)
    assert float(snapshot.raw_market["close"]) == float(target.close)
    assert float(snapshot.features["rolling_high_distance"]) < 0.1


def test_rsi_calculation(feature_db):
    start = datetime(2026, 2, 1)
    rows = []
    for i in range(30):
        close = Decimal(100 + i)
        row = OHLCVCandle(exchange="binance", symbol="UP/USDT", timeframe="1h",
            open_time=start + timedelta(hours=i), open=close-1, high=close+1, low=close-2,
            close=close, volume=Decimal("1000"), is_closed=True)
        feature_db.add(row); rows.append(row)
    feature_db.commit()
    snapshot = MarketFeatureService(feature_db).generate(_request(rows[-1]))
    assert float(snapshot.features["rsi"]) == pytest.approx(100.0)


def test_macd_calculation(feature_db):
    rows = _seed_candles(feature_db, 60)
    snapshot = MarketFeatureService(feature_db).generate(_request(rows[-1]))
    assert snapshot.features["macd"] is not None
    assert snapshot.features["macd_signal"] is not None
    assert snapshot.features["macd_histogram"] is not None
    assert float(snapshot.features["macd"]) > 0


def test_sma_ema_features(feature_db):
    rows = _seed_candles(feature_db, 40)
    snapshot = MarketFeatureService(feature_db).generate(_request(rows[-1]))
    closes = [float(row.close) for row in rows]
    expected_sma = sum(closes[-10:]) / 10
    assert float(snapshot.features["sma_fast"]) == pytest.approx(expected_sma)
    assert snapshot.features["sma_slow"] is not None
    assert snapshot.features["ema_fast"] is not None
    assert snapshot.features["ema_slow"] is not None
    assert snapshot.features["moving_average_distance"] is not None
    assert snapshot.features["moving_average_slope"] is not None


def test_volatility_feature(feature_db):
    rows = _seed_candles(feature_db, 40)
    snapshot = MarketFeatureService(feature_db).generate(_request(rows[-1]))
    assert snapshot.features["volatility"] is not None
    assert float(snapshot.features["volatility"]) > 0
    assert snapshot.features["atr"] is not None
    assert float(snapshot.features["true_range"]) > 0


def test_candle_structure_features(feature_db):
    rows = _seed_candles(feature_db, 40)
    target = rows[-1]
    snapshot = MarketFeatureService(feature_db).generate(_request(target))
    assert float(snapshot.features["candle_body_size"]) == pytest.approx(abs(float(target.close-target.open)))
    assert float(snapshot.features["upper_wick"]) == pytest.approx(float(target.high-max(target.open, target.close)))
    assert float(snapshot.features["lower_wick"]) == pytest.approx(float(min(target.open, target.close)-target.low))
    assert float(snapshot.features["candle_range"]) == pytest.approx(float(target.high-target.low))
    assert 0 <= float(snapshot.features["range_percentile"]) <= 1


def test_symbol_selection_context_inclusion(feature_db):
    rows = _seed_candles(feature_db, 40)
    target = rows[-1]
    run = SymbolSelectionRun(
        exchange="binance", configuration={}, weights={}, lookback=20,
        target_volatility=Decimal("0.5"), volatility_tolerance=Decimal("0.5"),
        winsor_percentiles={"low": 0.01, "high": 0.99}, scanned_count=1, eligible_count=1,
        selected_count=0, rejected_count=1, started_at=target.open_time-timedelta(minutes=2),
        completed_at=target.open_time-timedelta(minutes=1),
    )
    feature_db.add(run); feature_db.flush()
    result = SymbolSelectionResult(
        run_id=run.id, symbol=target.symbol, selected=False, rank=None, score=Decimal("0.42"),
        raw_metrics={"quote_volume": 2500000, "spread_pct": 0.001},
        norm_metrics={"liquidity": 0.8, "spread_quality": 0.9, "volatility_suitability": 0.7, "activity": 0.6},
        score_components={}, rejection_reasons=["spread_too_wide"], created_at=target.open_time-timedelta(minutes=1),
    )
    feature_db.add(result); feature_db.commit()
    snapshot = MarketFeatureService(feature_db).generate(_request(target))
    assert snapshot.market_quality["selection_status"] == "rejected"
    assert snapshot.market_quality["rejection_reasons"] == ["spread_too_wide"]
    assert float(snapshot.market_quality["selection_score"]) == pytest.approx(0.42)
    assert float(snapshot.raw_market["quote_volume"]) == pytest.approx(2500000)


def test_observation_link_and_context_fallback(feature_db):
    rows = _seed_candles(feature_db, 40)
    target = rows[-1]
    observation = ResearchObservation(
        event_type="symbol_selected", source="symbol_selection", exchange="binance", symbol=target.symbol,
        timeframe="1h", candle_open_time=target.open_time, spread=Decimal("0.002"),
        selection_score=Decimal("0.88"), selection_status="selected", selection_reasons=[],
        market_context={"quote_volume": 123456, "liquidity": 0.75}, observed_at=target.open_time,
    )
    feature_db.add(observation); feature_db.commit()
    snapshot = MarketFeatureService(feature_db).generate(_request(target))
    assert snapshot.observation_event_id == observation.event_id
    assert snapshot.market_quality["selection_status"] == "selected"
    assert float(snapshot.raw_market["spread"]) == pytest.approx(0.002)
    assert float(snapshot.raw_market["quote_volume"]) == pytest.approx(123456)


def test_canonical_configuration_hash():
    a = {"b": 2, "a": 1, "nested": {"z": 3, "x": 4}}
    b = {"nested": {"x": 4, "z": 3}, "a": 1, "b": 2}
    assert canonical_configuration_hash(a) == canonical_configuration_hash(b)
    assert len(canonical_configuration_hash(a)) == 64


def test_duplicate_generation_idempotency(feature_db):
    rows = _seed_candles(feature_db, 40)
    service = MarketFeatureService(feature_db)
    first = service.generate(_request(rows[-1]))
    second = service.generate(_request(rows[-1]))
    count = feature_db.execute(select(func.count()).select_from(MarketFeatureSnapshot)).scalar_one()
    assert first.id == second.id
    assert count == 1


def test_feature_retrieval_and_filtering_is_deterministic(feature_db):
    rows = _seed_candles(feature_db, 45)
    service = MarketFeatureService(feature_db)
    a = service.generate(_request(rows[-2]))
    b = service.generate(_request(rows[-1]))
    assert service.get(a.id).id == a.id
    found = service.list(symbol="btc/usdt", timeframe="1h", feature_version="1.0.0",
                         start=rows[-2].open_time, end=rows[-1].open_time)
    assert [item.id for item in found] == [a.id, b.id]


def test_research_feature_engine_cannot_trigger_trade_or_order_execution(feature_db):
    service = MarketFeatureService(feature_db)
    forbidden = {"submit_order", "create_order", "execute_order", "place_order", "decrypt_credentials", "approve_risk"}
    assert forbidden.isdisjoint(set(dir(service)))
    import packages.research.features as feature_module
    source_names = set(feature_module.__dict__)
    assert "DemoOrderEngine" not in source_names
    assert "ExchangeAdapter" not in source_names
    assert "RiskEngine" not in source_names
