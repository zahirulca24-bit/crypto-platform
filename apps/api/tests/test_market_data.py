from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from main import app
from database import SessionLocal
from models import OHLCVCandle
from exchange.adapter import CCXTMarketDataAdapter
from services.market_data import sync_market_data

client = TestClient(app)


def create_mock_adapter():
    mock_ccxt = MagicMock()

    # Raw CCXT OHLCV sample format: [timestamp_ms, open, high, low, close, volume]
    mock_raw_ohlcv = [
        [1700000000000, "35000.50", "35500.00", "34900.00", "35200.25", "150.50"],
        [1700003600000, "35200.25", "35800.00", "35100.00", "35700.75", "200.10"],
        [1700007200000, "35700.75", "36000.00", "35600.00", "35900.00", "180.30"],
    ]

    mock_ccxt.fetch_ohlcv.return_value = mock_raw_ohlcv
    mock_ccxt.fetch_ticker.return_value = {
        "symbol": "BTC/USDT",
        "last": "35900.00",
        "bid": "35899.00",
        "ask": "35901.00",
        "baseVolume": "180.30",
        "timestamp": 1700007200000,
    }
    mock_ccxt.load_markets.return_value = {
        "BTC/USDT": {"base": "BTC", "quote": "USDT", "active": True}
    }

    adapter = CCXTMarketDataAdapter(
        exchange_id="binance", exchange_instance=mock_ccxt
    )
    return adapter


def test_connector_fetch_success_and_decimal_conversion():
    adapter = create_mock_adapter()
    candles = adapter.fetch_ohlcv("BTC/USDT", "1h", 10)

    assert len(candles) == 3
    for c in candles:
        assert isinstance(c["open"], Decimal)
        assert isinstance(c["high"], Decimal)
        assert isinstance(c["low"], Decimal)
        assert isinstance(c["close"], Decimal)
        assert isinstance(c["volume"], Decimal)
        assert isinstance(c["open_time"], datetime)
        assert c["exchange"] == "binance"
        assert c["symbol"] == "BTC/USDT"


def test_candle_persistence_and_duplicate_prevention():
    adapter = create_mock_adapter()
    db = SessionLocal()
    try:
        # Clean up any pre-existing test candles for isolation
        db.query(OHLCVCandle).filter(
            OHLCVCandle.exchange == "binance",
            OHLCVCandle.symbol == "BTC/USDT",
            OHLCVCandle.timeframe == "1h",
        ).delete()
        db.commit()

        # First sync
        res1 = sync_market_data(
            db,
            exchange_id="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            limit=10,
            adapter=adapter,
        )
        assert res1["fetched_count"] == 3
        assert res1["inserted_count"] == 2

        # Verify DB rows
        rows = (
            db.query(OHLCVCandle)
            .filter(
                OHLCVCandle.exchange == "binance",
                OHLCVCandle.symbol == "BTC/USDT",
                OHLCVCandle.timeframe == "1h",
            )
            .all()
        )
        assert len(rows) == 2
        for r in rows:
            assert isinstance(r.open, Decimal)
            assert isinstance(r.close, Decimal)

        # Repeat sync with identical data -> should insert 0 new rows and skip all
        res2 = sync_market_data(
            db,
            exchange_id="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            limit=10,
            adapter=adapter,
        )
        assert res2["inserted_count"] == 0
        assert res2["skipped_count"] == 3

        # Confirm DB still has 2 rows (no duplicate rows created)
        rows_after = (
            db.query(OHLCVCandle)
            .filter(
                OHLCVCandle.exchange == "binance",
                OHLCVCandle.symbol == "BTC/USDT",
                OHLCVCandle.timeframe == "1h",
            )
            .all()
        )
        assert len(rows_after) == 2
    finally:
        db.close()


def test_ohlcv_read_api():
    response = client.get(
        "/v1/market-data/ohlcv?exchange=binance&symbol=BTC/USDT&timeframe=1h&limit=10"
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 2
    candle = data[0]
    assert candle["exchange"] == "binance"
    assert candle["symbol"] == "BTC/USDT"
    assert "open" in candle
    assert "close" in candle


def test_invalid_symbol_handling():
    # Invalid symbol format without slash
    response = client.get(
        "/v1/market-data/ohlcv?exchange=binance&symbol=INVALIDSYMBOL&timeframe=1h"
    )
    assert response.status_code == 200  # returns empty list for DB query
    assert response.json() == []

    # Sync endpoint with invalid symbol format
    sync_resp = client.post(
        "/v1/market-data/sync",
        json={
            "exchange": "binance",
            "symbol": "INVALIDSYMBOL",
            "timeframe": "1h",
            "limit": 10,
        },
    )
    assert sync_resp.status_code == 422


def test_invalid_timeframe_handling():
    sync_resp = client.post(
        "/v1/market-data/sync",
        json={
            "exchange": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "invalid_tf",
            "limit": 10,
        },
    )
    assert sync_resp.status_code == 422


def test_exchange_failure_handling_without_crashing_fastapi():
    mock_ccxt = MagicMock()
    mock_ccxt.fetch_ohlcv.side_effect = Exception("Exchange Connection Timeout")
    failing_adapter = CCXTMarketDataAdapter(
        exchange_id="binance", exchange_instance=mock_ccxt
    )

    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError, match="Failed to fetch OHLCV"):
            failing_adapter.fetch_ohlcv("BTC/USDT", "1h")
    finally:
        db.close()

    # Verify FastAPI server remains completely responsive
    health_resp = client.get("/health")
    assert health_resp.status_code == 200


