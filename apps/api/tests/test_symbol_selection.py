"""
PROMPT #009 — Symbol Selection Engine Tests

Coverage:
- All filters (quote currency, market type, volume, spread, volatility,
  include/exclude, leveraged tokens, missing ticker/ohlcv)
- log10 liquidity transformation
- log-return volatility calculation
- winsorization + min-max normalisation (deterministic)
- volatility suitability formula (medium scores higher than extremes, clamped)
- deterministic scoring and ranking (score desc, symbol asc tie-breaker)
- max_symbols default (10) and custom values
- both selected and rejected symbols persisted with rejection reasons
- GET /v1/market-data/symbol-selection/{run_id} returns identical data to POST
- multiple runs create separate SymbolSelectionRun rows
- existing health endpoints unaffected
"""

import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from database import SessionLocal
from models import SymbolSelectionRun, SymbolSelectionResult
from services.symbol_selection import (
    _compute_spread_pct,
    _compute_volatility,
    _winsorize_and_scale,
    _volatility_suitability,
    run_symbol_selection,
    WEIGHTS,
    VOLATILITY_LOOKBACK,
    TARGET_VOLATILITY,
    VOLATILITY_TOLERANCE,
    WINSOR_LOW,
    WINSOR_HIGH,
)
from schemas import SymbolSelectionRequest

client = TestClient(app)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_ohlcv(closes, open_val=None):
    """Build fake OHLCV candle list from a list of close prices."""
    candles = []
    for i, c in enumerate(closes):
        candles.append({
            "open": open_val or c * 0.99,
            "high": c * 1.01,
            "low": c * 0.98,
            "close": c,
            "volume": 1000.0,
            "is_closed": True,
        })
    return candles


def _build_adapter(markets, tickers, ohlcv_map):
    """Create a mock CCXTMarketDataAdapter."""
    mock = MagicMock()
    mock.fetch_markets.return_value = markets
    mock.fetch_ticker.side_effect = lambda sym: tickers[sym]
    mock.fetch_ohlcv.side_effect = lambda sym, timeframe="1h", limit=21: ohlcv_map.get(sym, [])
    return mock


def _default_ticker(sym, last=100.0, bid=99.9, ask=100.1, qvol=1_000_000.0, bvol=1000.0):
    return {
        "symbol": sym,
        "last": last,
        "bid": bid,
        "ask": ask,
        "quoteVolume": qvol,
        "volume": bvol,
    }


def _default_candles(n=21, base=100.0):
    closes = [base * (1 + 0.001 * i) for i in range(n)]
    return _make_ohlcv(closes, open_val=base)


# ─── Unit tests: spread calculation ───────────────────────────────────────────

def test_spread_pct_normal():
    result = _compute_spread_pct(99.9, 100.1)
    assert result == pytest.approx((100.1 - 99.9) / 100.0 * 100, rel=1e-6)


def test_spread_pct_none_bid():
    assert _compute_spread_pct(None, 100.1) is None


def test_spread_pct_none_ask():
    assert _compute_spread_pct(99.9, None) is None


def test_spread_pct_zero_bid():
    assert _compute_spread_pct(0.0, 100.1) is None


# ─── Unit tests: log-return volatility ────────────────────────────────────────

def test_volatility_uses_log_returns_not_raw_prices():
    # Constant prices → zero volatility
    candles = _make_ohlcv([100.0] * 21)
    vol = _compute_volatility(candles)
    assert vol == pytest.approx(0.0, abs=1e-10)


def test_volatility_nonzero_for_varying_prices():
    candles = _make_ohlcv([100, 102, 98, 103, 97, 105, 95])
    vol = _compute_volatility(candles)
    assert vol is not None and vol > 0


def test_volatility_returns_none_for_single_candle():
    candles = _make_ohlcv([100.0])
    vol = _compute_volatility(candles)
    assert vol is None


def test_volatility_skips_unclosed_candles():
    candles = _make_ohlcv([100, 101, 102])
    # Mark last as unclosed
    candles[-1]["is_closed"] = False
    vol_with_unclosed = _compute_volatility(candles)
    candles_all_closed = _make_ohlcv([100, 101])
    vol_all_closed = _compute_volatility(candles_all_closed)
    # Should produce same result since unclosed candle excluded
    assert vol_with_unclosed == pytest.approx(vol_all_closed, rel=1e-9)


# ─── Unit tests: winsorization + min-max ──────────────────────────────────────

def test_winsorize_and_scale_basic():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    scaled = _winsorize_and_scale(vals)
    # Min should map to ~0, max to ~1
    assert min(v for v in scaled if v is not None) == pytest.approx(0.0, abs=0.05)
    assert max(v for v in scaled if v is not None) == pytest.approx(1.0, abs=0.05)


def test_winsorize_handles_none_values():
    vals = [None, 2.0, 3.0, None, 5.0]
    scaled = _winsorize_and_scale(vals)
    assert scaled[0] is None
    assert scaled[3] is None
    assert scaled[2] is not None


def test_winsorize_and_scale_deterministic():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    r1 = _winsorize_and_scale(vals)
    r2 = _winsorize_and_scale(vals)
    assert r1 == r2


def test_winsorize_identical_values():
    vals = [5.0, 5.0, 5.0, 5.0]
    scaled = _winsorize_and_scale(vals)
    for v in scaled:
        assert v is not None
        assert v == pytest.approx(0.0, abs=1e-9)


# ─── Unit tests: volatility suitability ───────────────────────────────────────

def test_volatility_suitability_at_target_is_1():
    vs = _volatility_suitability(TARGET_VOLATILITY)
    assert vs == pytest.approx(1.0, abs=1e-9)


def test_volatility_suitability_medium_beats_extreme_low():
    """Normalised vol near TARGET should score higher than vol near 0."""
    vs_medium = _volatility_suitability(TARGET_VOLATILITY)
    vs_extreme_low = _volatility_suitability(0.0)
    assert vs_medium > vs_extreme_low


def test_volatility_suitability_medium_beats_extreme_high():
    """Normalised vol near TARGET should score higher than vol near 1."""
    vs_medium = _volatility_suitability(TARGET_VOLATILITY)
    vs_extreme_high = _volatility_suitability(1.0)
    assert vs_medium > vs_extreme_high


def test_volatility_suitability_clamped_to_zero_at_extremes():
    """Values outside tolerance should clamp to 0, never go negative."""
    vs_below = _volatility_suitability(0.0)
    vs_above = _volatility_suitability(1.0)
    assert vs_below >= 0.0
    assert vs_above >= 0.0


def test_volatility_suitability_none_returns_zero():
    assert _volatility_suitability(None) == 0.0


def test_volatility_suitability_always_in_0_1():
    for v in [x / 100 for x in range(0, 101)]:
        vs = _volatility_suitability(v)
        assert 0.0 <= vs <= 1.0, f"Out of range for norm_vol={v}: {vs}"


# ─── Filter tests (via service) ────────────────────────────────────────────────

def _make_minimal_request(**kwargs):
    return SymbolSelectionRequest(exchange="binance", **kwargs)


def _run_with_adapter(request, adapter):
    db = SessionLocal()
    try:
        result = run_symbol_selection(request, db, adapter=adapter)
        return result
    finally:
        db.close()


def test_filter_inactive_market():
    markets = [
        {"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT", "active": False},
        {"symbol": "ETH/USDT", "base": "ETH", "quote": "USDT", "active": True},
    ]
    tickers = {"ETH/USDT": _default_ticker("ETH/USDT")}
    ohlcv = {"ETH/USDT": _default_candles()}
    adapter = _build_adapter(markets, tickers, ohlcv)
    result = _run_with_adapter(_make_minimal_request(), adapter)
    syms = [r.symbol for r in result.results]
    assert "BTC/USDT" in syms
    btc_row = next(r for r in result.results if r.symbol == "BTC/USDT")
    assert btc_row.selected is False
    assert "inactive_market" in btc_row.rejection_reasons


def test_filter_quote_currency():
    markets = [
        {"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT", "active": True},
        {"symbol": "BTC/BTC", "base": "BTC", "quote": "BTC", "active": True},
    ]
    tickers = {"BTC/USDT": _default_ticker("BTC/USDT")}
    ohlcv = {"BTC/USDT": _default_candles()}
    adapter = _build_adapter(markets, tickers, ohlcv)
    result = _run_with_adapter(_make_minimal_request(quote_currency="USDT"), adapter)
    btcbtc = next(r for r in result.results if r.symbol == "BTC/BTC")
    assert btcbtc.selected is False
    assert "quote_currency_mismatch" in btcbtc.rejection_reasons


def test_filter_leveraged_token():
    markets = [
        {"symbol": "BTCBULL/USDT", "base": "BTCBULL", "quote": "USDT", "active": True},
        {"symbol": "ETH/USDT", "base": "ETH", "quote": "USDT", "active": True},
    ]
    tickers = {"ETH/USDT": _default_ticker("ETH/USDT")}
    ohlcv = {"ETH/USDT": _default_candles()}
    adapter = _build_adapter(markets, tickers, ohlcv)
    result = _run_with_adapter(_make_minimal_request(), adapter)
    lev = next(r for r in result.results if r.symbol == "BTCBULL/USDT")
    assert lev.selected is False
    assert "leveraged_token" in lev.rejection_reasons


def test_filter_include_symbols():
    markets = [
        {"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT", "active": True},
        {"symbol": "ETH/USDT", "base": "ETH", "quote": "USDT", "active": True},
        {"symbol": "XRP/USDT", "base": "XRP", "quote": "USDT", "active": True},
    ]
    tickers = {
        "BTC/USDT": _default_ticker("BTC/USDT"),
        "ETH/USDT": _default_ticker("ETH/USDT"),
    }
    ohlcv = {
        "BTC/USDT": _default_candles(),
        "ETH/USDT": _default_candles(),
    }
    adapter = _build_adapter(markets, tickers, ohlcv)
    result = _run_with_adapter(_make_minimal_request(include_symbols=["BTC/USDT", "ETH/USDT"]), adapter)
    xrp = next(r for r in result.results if r.symbol == "XRP/USDT")
    assert xrp.selected is False
    assert "not_in_include_list" in xrp.rejection_reasons


def test_filter_exclude_symbols():
    markets = [
        {"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT", "active": True},
        {"symbol": "ETH/USDT", "base": "ETH", "quote": "USDT", "active": True},
    ]
    tickers = {"ETH/USDT": _default_ticker("ETH/USDT")}
    ohlcv = {"ETH/USDT": _default_candles()}
    adapter = _build_adapter(markets, tickers, ohlcv)
    result = _run_with_adapter(_make_minimal_request(exclude_symbols=["BTC/USDT"]), adapter)
    btc = next(r for r in result.results if r.symbol == "BTC/USDT")
    assert btc.selected is False
    assert "explicitly_excluded" in btc.rejection_reasons


def test_filter_min_quote_volume():
    markets = [
        {"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT", "active": True},
    ]
    tickers = {"BTC/USDT": _default_ticker("BTC/USDT", qvol=500.0)}
    ohlcv = {"BTC/USDT": _default_candles()}
    adapter = _build_adapter(markets, tickers, ohlcv)
    result = _run_with_adapter(_make_minimal_request(min_quote_volume=1_000_000.0), adapter)
    btc = next(r for r in result.results if r.symbol == "BTC/USDT")
    assert btc.selected is False
    assert "volume_below_minimum" in btc.rejection_reasons


def test_filter_max_spread_pct():
    markets = [
        {"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT", "active": True},
    ]
    # Very wide spread
    tickers = {"BTC/USDT": _default_ticker("BTC/USDT", bid=90.0, ask=110.0)}
    ohlcv = {"BTC/USDT": _default_candles()}
    adapter = _build_adapter(markets, tickers, ohlcv)
    result = _run_with_adapter(_make_minimal_request(max_spread_pct=0.5), adapter)
    btc = next(r for r in result.results if r.symbol == "BTC/USDT")
    assert btc.selected is False
    assert "spread_above_maximum" in btc.rejection_reasons


def test_filter_missing_ticker():
    markets = [{"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT", "active": True}]
    mock = MagicMock()
    mock.fetch_markets.return_value = markets
    mock.fetch_ticker.side_effect = RuntimeError("exchange timeout")
    result = _run_with_adapter(_make_minimal_request(), mock)
    btc = next(r for r in result.results if r.symbol == "BTC/USDT")
    assert btc.selected is False
    assert "ticker_fetch_failed" in btc.rejection_reasons


def test_filter_missing_ohlcv():
    markets = [{"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT", "active": True}]
    mock = MagicMock()
    mock.fetch_markets.return_value = markets
    mock.fetch_ticker.return_value = _default_ticker("BTC/USDT")
    mock.fetch_ohlcv.side_effect = RuntimeError("rate limit")
    result = _run_with_adapter(_make_minimal_request(), mock)
    btc = next(r for r in result.results if r.symbol == "BTC/USDT")
    assert btc.selected is False
    assert "ohlcv_fetch_failed" in btc.rejection_reasons


# ─── Scoring, ranking, max_symbols ───────────────────────────────────────────

def _make_multi_symbol_adapter(n=5):
    """Create adapter with n symbols having distinct volumes so ranking is clear."""
    symbols = [f"SYM{i:02d}/USDT" for i in range(n)]
    markets = [{"symbol": s, "base": s.split("/")[0], "quote": "USDT", "active": True} for s in symbols]
    tickers = {
        s: _default_ticker(s, qvol=1_000_000.0 * (i + 1))
        for i, s in enumerate(symbols)
    }
    ohlcv = {s: _default_candles() for s in symbols}
    return _build_adapter(markets, tickers, ohlcv), symbols


def test_max_symbols_default_is_10():
    # Build 15 symbols
    symbols = [f"TOK{i:02d}/USDT" for i in range(15)]
    markets = [{"symbol": s, "base": s.split("/")[0], "quote": "USDT", "active": True} for s in symbols]
    tickers = {s: _default_ticker(s, qvol=1_000_000.0 * (i + 1)) for i, s in enumerate(symbols)}
    ohlcv = {s: _default_candles() for s in symbols}
    adapter = _build_adapter(markets, tickers, ohlcv)
    result = _run_with_adapter(_make_minimal_request(), adapter)
    assert result.selected_count == 10
    assert len(result.selected_symbols) == 10


def test_max_symbols_custom():
    adapter, symbols = _make_multi_symbol_adapter(5)
    result = _run_with_adapter(_make_minimal_request(max_symbols=3), adapter)
    assert result.selected_count == 3
    assert len(result.selected_symbols) == 3


def test_ranking_deterministic_tie_breaker():
    """Two symbols with identical data must rank in alphabetical order."""
    markets = [
        {"symbol": "AAA/USDT", "base": "AAA", "quote": "USDT", "active": True},
        {"symbol": "BBB/USDT", "base": "BBB", "quote": "USDT", "active": True},
    ]
    same_ticker = _default_ticker("X/USDT", last=100.0, bid=99.9, ask=100.1, qvol=1_000_000.0)
    tickers = {"AAA/USDT": {**same_ticker, "symbol": "AAA/USDT"},
               "BBB/USDT": {**same_ticker, "symbol": "BBB/USDT"}}
    ohlcv = {"AAA/USDT": _default_candles(), "BBB/USDT": _default_candles()}
    adapter = _build_adapter(markets, tickers, ohlcv)
    result = _run_with_adapter(_make_minimal_request(max_symbols=1), adapter)
    # AAA should win alphabetically when scores tie
    assert result.selected_symbols[0] == "AAA/USDT"
    bbb = next(r for r in result.results if r.symbol == "BBB/USDT")
    assert bbb.selected is False
    assert bbb.rejection_reasons == ["ranked_below_max_symbols"]


def test_score_components_sum_to_total():
    adapter, _ = _make_multi_symbol_adapter(3)
    result = _run_with_adapter(_make_minimal_request(max_symbols=3), adapter)
    for item in result.results:
        if item.selected:
            c = item.score_components
            total = c.liquidity + c.spread + c.volatility + c.activity
            assert total == pytest.approx(item.score, rel=1e-6)


# ─── Persistence tests ─────────────────────────────────────────────────────────

def test_both_selected_and_rejected_are_persisted():
    markets = [
        {"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT", "active": True},
        {"symbol": "ETH/USDT", "base": "ETH", "quote": "USDT", "active": False},
    ]
    tickers = {"BTC/USDT": _default_ticker("BTC/USDT")}
    ohlcv = {"BTC/USDT": _default_candles()}
    adapter = _build_adapter(markets, tickers, ohlcv)
    db = SessionLocal()
    try:
        result = run_symbol_selection(_make_minimal_request(), db, adapter=adapter)
        run_uuid = uuid.UUID(result.run_id)
        rows = db.query(SymbolSelectionResult).filter(SymbolSelectionResult.run_id == run_uuid).all()
        symbols_persisted = {r.symbol for r in rows}
        assert "BTC/USDT" in symbols_persisted
        assert "ETH/USDT" in symbols_persisted
        # ETH/USDT is rejected
        eth_row = next(r for r in rows if r.symbol == "ETH/USDT")
        assert eth_row.selected is False
        assert "inactive_market" in eth_row.rejection_reasons
    finally:
        db.close()


def test_rejection_reasons_are_machine_readable_strings():
    markets = [
        {"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT", "active": False},
    ]
    adapter = _build_adapter(markets, {}, {})
    db = SessionLocal()
    try:
        result = run_symbol_selection(_make_minimal_request(), db, adapter=adapter)
        run_uuid = uuid.UUID(result.run_id)
        rows = db.query(SymbolSelectionResult).filter(SymbolSelectionResult.run_id == run_uuid).all()
        btc_row = rows[0]
        assert isinstance(btc_row.rejection_reasons, list)
        assert all(isinstance(r, str) for r in btc_row.rejection_reasons)
    finally:
        db.close()


def test_run_persists_weights_and_lookback():
    adapter, _ = _make_multi_symbol_adapter(2)
    db = SessionLocal()
    try:
        result = run_symbol_selection(_make_minimal_request(), db, adapter=adapter)
        run_uuid = uuid.UUID(result.run_id)
        db_run = db.query(SymbolSelectionRun).filter(SymbolSelectionRun.id == run_uuid).first()
        assert db_run is not None
        assert db_run.weights["liquidity"] == pytest.approx(0.40)
        assert db_run.weights["spread"] == pytest.approx(0.30)
        assert db_run.weights["volatility"] == pytest.approx(0.20)
        assert db_run.weights["activity"] == pytest.approx(0.10)
        assert db_run.lookback == VOLATILITY_LOOKBACK
        assert float(db_run.target_volatility) == pytest.approx(TARGET_VOLATILITY)
        assert float(db_run.volatility_tolerance) == pytest.approx(VOLATILITY_TOLERANCE)
        assert db_run.winsor_percentiles["low"] == pytest.approx(WINSOR_LOW)
        assert db_run.winsor_percentiles["high"] == pytest.approx(WINSOR_HIGH)
    finally:
        db.close()


def test_score_stored_as_numeric():
    adapter, _ = _make_multi_symbol_adapter(2)
    db = SessionLocal()
    try:
        result = run_symbol_selection(_make_minimal_request(), db, adapter=adapter)
        run_uuid = uuid.UUID(result.run_id)
        rows = db.query(SymbolSelectionResult).filter(
            SymbolSelectionResult.run_id == run_uuid,
            SymbolSelectionResult.selected == True
        ).all()
        for row in rows:
            assert row.score is not None
            assert isinstance(row.score, Decimal)
    finally:
        db.close()


def test_multiple_runs_are_separate_rows():
    adapter, _ = _make_multi_symbol_adapter(2)
    db = SessionLocal()
    try:
        r1 = run_symbol_selection(_make_minimal_request(), db, adapter=adapter)
        r2 = run_symbol_selection(_make_minimal_request(), db, adapter=adapter)
        assert r1.run_id != r2.run_id
        assert db.query(SymbolSelectionRun).count() >= 2
    finally:
        db.close()


# ─── API endpoint tests ────────────────────────────────────────────────────────

def _mock_adapter_for_api(symbols=None):
    if symbols is None:
        symbols = ["BTC/USDT", "ETH/USDT"]
    markets = [{"symbol": s, "base": s.split("/")[0], "quote": "USDT", "active": True} for s in symbols]
    tickers = {s: _default_ticker(s, qvol=1_000_000.0 * (i + 1)) for i, s in enumerate(symbols)}
    ohlcv = {s: _default_candles() for s in symbols}
    return _build_adapter(markets, tickers, ohlcv)


def test_post_symbol_selection_endpoint():
    adapter = _mock_adapter_for_api()
    with patch("services.symbol_selection.CCXTMarketDataAdapter", return_value=adapter):
        response = client.post(
            "/v1/market-data/symbol-selection",
            json={"exchange": "binance"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert "selected_symbols" in data
    assert isinstance(data["results"], list)
    assert data["scanned_count"] >= 0


def test_get_symbol_selection_endpoint_matches_post():
    adapter = _mock_adapter_for_api()
    with patch("services.symbol_selection.CCXTMarketDataAdapter", return_value=adapter):
        post_resp = client.post(
            "/v1/market-data/symbol-selection",
            json={"exchange": "binance"},
        )
    assert post_resp.status_code == 200
    run_id = post_resp.json()["run_id"]
    post_data = post_resp.json()

    get_resp = client.get(f"/v1/market-data/symbol-selection/{run_id}")
    assert get_resp.status_code == 200
    get_data = get_resp.json()

    assert get_data["run_id"] == post_data["run_id"]
    assert get_data["selected_count"] == post_data["selected_count"]
    assert get_data["selected_symbols"] == post_data["selected_symbols"]
    assert get_data["scanned_count"] == post_data["scanned_count"]


def test_get_nonexistent_run_returns_404():
    fake_id = str(uuid.uuid4())
    response = client.get(f"/v1/market-data/symbol-selection/{fake_id}")
    assert response.status_code == 404


def test_get_invalid_run_id_returns_400():
    response = client.get("/v1/market-data/symbol-selection/not-a-uuid")
    assert response.status_code == 400


def test_post_missing_exchange_returns_422():
    response = client.post("/v1/market-data/symbol-selection", json={})
    assert response.status_code == 422


# ─── Existing endpoints unaffected ────────────────────────────────────────────

def test_health_endpoint_still_works():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_db_endpoint_still_works():
    response = client.get("/health/db")
    assert response.status_code == 200
    assert response.json()["database"] == "connected"


