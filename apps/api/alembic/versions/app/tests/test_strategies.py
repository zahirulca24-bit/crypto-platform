import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math

from database import SessionLocal
from main import app
from models import OHLCVCandle, StrategyDecision
from indicators import calculate_sma, calculate_ema, calculate_macd, calculate_rsi

@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

client = TestClient(app)

def test_evaluate_endpoint_unknown_strategy():
    response = client.post(
        '/v1/strategies/evaluate?strategy_name=unknown',
        json={
            'request': {
                'exchange': 'binance',
                'symbol': 'BTC/USDT',
                'timeframe': '1h'
            },
            'config': {}
        }
    )
    assert response.status_code == 400

def _populate_candles(db: Session, prices, exchange='binance', symbol='TEST/USDT', is_closed=True):
    now = datetime.now(timezone.utc)
    for i, p in enumerate(prices):
        c = OHLCVCandle(
            exchange=exchange,
            symbol=symbol,
            timeframe='1h',
            open_time=now - timedelta(hours=len(prices)-i),
            open=p,
            high=p+1,
            low=p-1,
            close=p,
            volume=100,
            is_closed=is_closed
        )
        db.add(c)
    db.commit()

def test_rsi_buy_sell_no_signal(db_session: Session):
    db_session.query(OHLCVCandle).delete()
    db_session.query(StrategyDecision).delete()
    db_session.commit()
    
    # BUY: RSI was 100 then drops to 27.7
    prices = [100]
    for _ in range(10): prices.append(prices[-1] * 1.01)
    prices.append(prices[-1] * 0.9)
    _populate_candles(db_session, prices, symbol='RSI_BUY')
    
    res = client.post(
        '/v1/strategies/evaluate?strategy_name=rsi_transition',
        json={'request': {'exchange': 'binance', 'symbol': 'RSI_BUY', 'timeframe': '1h'}, 'config': {'length': 5, 'oversold': 30}}
    )
    assert res.status_code == 200
    data = res.json()
    assert data['decision'] == 'BUY'
    assert 'current_rsi' in data['indicator_values']
    assert 'previous_rsi' in data['indicator_values']
    assert data['proposal']['action'] == 'BUY'
    assert data['proposal']['sizing_intent'] == 'risk_engine_default'
    
    # SELL: RSI was 0 then jumps to 70.5
    db_session.query(OHLCVCandle).delete()
    prices = [100]
    for _ in range(10): prices.append(prices[-1] * 0.99)
    prices.append(prices[-1] * 1.1)
    _populate_candles(db_session, prices, symbol='RSI_SELL')
    res = client.post(
        '/v1/strategies/evaluate?strategy_name=rsi_transition',
        json={'request': {'exchange': 'binance', 'symbol': 'RSI_SELL', 'timeframe': '1h'}, 'config': {'length': 5, 'overbought': 70}}
    )
    assert res.status_code == 200
    data = res.json()
    assert data['decision'] == 'SELL'
    assert data['proposal']['action'] == 'SELL'
    
    # HOLD
    db_session.query(OHLCVCandle).delete()
    prices = [50] * 20
    _populate_candles(db_session, prices, symbol='RSI_HOLD')
    res = client.post(
        '/v1/strategies/evaluate?strategy_name=rsi_transition',
        json={'request': {'exchange': 'binance', 'symbol': 'RSI_HOLD', 'timeframe': '1h'}, 'config': {'length': 5}}
    )
    data = res.json()
    assert data['decision'] == 'HOLD'
    assert data['proposal'] is None

def test_macd_buy_sell_crossover(db_session: Session):
    db_session.query(OHLCVCandle).delete()
    db_session.query(StrategyDecision).delete()
    db_session.commit()
    
    # BUY
    prices = [100 + 10 * math.sin(i * 0.5) for i in range(11)]
    _populate_candles(db_session, prices, symbol='MACD_BUY')
    res = client.post(
        '/v1/strategies/evaluate?strategy_name=macd_crossover',
        json={'request': {'exchange': 'binance', 'symbol': 'MACD_BUY', 'timeframe': '1h'}, 'config': {'fast': 3, 'slow': 5, 'signal': 2}}
    )
    assert res.status_code == 200
    data = res.json()
    assert data['decision'] == 'BUY'
    assert 'histogram' in data['indicator_values']
    
    # SELL
    db_session.query(OHLCVCandle).delete()
    prices = [100 + 10 * math.sin(i * 0.5) for i in range(18)]
    _populate_candles(db_session, prices, symbol='MACD_SELL')
    res = client.post(
        '/v1/strategies/evaluate?strategy_name=macd_crossover',
        json={'request': {'exchange': 'binance', 'symbol': 'MACD_SELL', 'timeframe': '1h'}, 'config': {'fast': 3, 'slow': 5, 'signal': 2}}
    )
    data = res.json()
    assert data['decision'] == 'SELL'

def test_ma_buy_sell_crossover(db_session: Session):
    db_session.query(OHLCVCandle).delete()
    db_session.query(StrategyDecision).delete()
    db_session.commit()
    
    # BUY
    prices = [100 + 10 * math.sin(i * 0.5) for i in range(13)]
    _populate_candles(db_session, prices, symbol='MA_BUY')
    res = client.post(
        '/v1/strategies/evaluate?strategy_name=ma_crossover',
        json={'request': {'exchange': 'binance', 'symbol': 'MA_BUY', 'timeframe': '1h'}, 'config': {'fast_len': 3, 'slow_len': 5, 'ma_type': 'sma'}}
    )
    data = res.json()
    assert data['decision'] == 'BUY'
    assert 'ma_type' in data['indicator_values']
    
    # SELL
    db_session.query(OHLCVCandle).delete()
    prices = [100 + 10 * math.sin(i * 0.5) for i in range(19)]
    _populate_candles(db_session, prices, symbol='MA_SELL')
    res = client.post(
        '/v1/strategies/evaluate?strategy_name=ma_crossover',
        json={'request': {'exchange': 'binance', 'symbol': 'MA_SELL', 'timeframe': '1h'}, 'config': {'fast_len': 3, 'slow_len': 5, 'ma_type': 'sma'}}
    )
    data = res.json()
    assert data['decision'] == 'SELL'

def test_deterministic_hash_and_idempotency(db_session: Session):
    db_session.query(OHLCVCandle).delete()
    db_session.query(StrategyDecision).delete()
    db_session.commit()
    
    prices = [10] * 20
    _populate_candles(db_session, prices, symbol='HASH_TEST')
    
    req_json = {'request': {'exchange': 'binance', 'symbol': 'HASH_TEST', 'timeframe': '1h'}, 'config': {'length': 5}}
    
    res1 = client.post('/v1/strategies/evaluate?strategy_name=rsi_transition', json=req_json)
    data1 = res1.json()
    
    # Verify deterministic full configuration hash
    full_config = {
        'strategy_name': 'rsi_transition',
        'strategy_version': '1.0.0',
        'configuration': {'length': 5}
    }
    expected_hash = hashlib.sha256(json.dumps(full_config, sort_keys=True).encode()).hexdigest()
    assert data1['configuration_hash'] == expected_hash
    
    # Second evaluation
    res2 = client.post('/v1/strategies/evaluate?strategy_name=rsi_transition', json=req_json)
    data2 = res2.json()
    
    assert data1['id'] == data2['id']
    count = db_session.query(StrategyDecision).count()
    assert count == 1

def test_non_closed_candles_ignored(db_session: Session):
    db_session.query(OHLCVCandle).delete()
    db_session.query(StrategyDecision).delete()
    db_session.commit()
    
    prices = [10] * 20
    _populate_candles(db_session, prices, symbol='IGNORE_TEST', is_closed=False)
    
    res = client.post(
        '/v1/strategies/evaluate?strategy_name=rsi_transition',
        json={'request': {'exchange': 'binance', 'symbol': 'IGNORE_TEST', 'timeframe': '1h'}, 'config': {'length': 5}}
    )
    assert res.status_code == 400

