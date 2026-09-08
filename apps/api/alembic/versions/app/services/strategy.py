
import hashlib
import json
from sqlalchemy.orm import Session
from sqlalchemy import select
from models import StrategyDecision, OHLCVCandle
from schemas import StrategyEvaluateRequest, StrategyDecisionResponse
from strategies import RSITransitionStrategy, MACDCrossoverStrategy, MACrossoverStrategy

STRATEGIES = {
    'rsi_transition': RSITransitionStrategy,
    'macd_crossover': MACDCrossoverStrategy,
    'ma_crossover': MACrossoverStrategy,
}

def evaluate_strategy(request: StrategyEvaluateRequest, strategy_name: str, config: dict, db: Session):
    strat_cls = STRATEGIES.get(strategy_name)
    if not strat_cls:
        raise ValueError(f'Unknown strategy: {strategy_name}')
        
    strat = strat_cls(**config)
    full_config = {
        'strategy_name': strategy_name,
        'strategy_version': strat.version,
        'configuration': config
    }
    config_hash = hashlib.sha256(json.dumps(full_config, sort_keys=True).encode()).hexdigest()

    # Get closed candles only up to the candle_open_time requested
    # We'll just fetch closed candles ordered by open_time
    stmt = (
        select(OHLCVCandle)
        .where(
            OHLCVCandle.exchange == request.exchange.lower(),
            OHLCVCandle.symbol == request.symbol,
            OHLCVCandle.timeframe == request.timeframe,
            OHLCVCandle.is_closed == True
        )
        .order_by(OHLCVCandle.open_time.asc())
        .limit(1000)
    )
    candles = db.execute(stmt).scalars().all()
    if not candles:
        raise ValueError('No closed candles found')

    latest_candle = candles[-1]
    
    # Check idempotent
    existing = db.execute(
        select(StrategyDecision).where(
            StrategyDecision.exchange == request.exchange.lower(),
            StrategyDecision.symbol == request.symbol,
            StrategyDecision.timeframe == request.timeframe,
            StrategyDecision.candle_open_time == latest_candle.open_time,
            StrategyDecision.strategy_name == strategy_name,
            StrategyDecision.configuration_hash == config_hash
        )
    ).scalar_one_or_none()
    
    if existing:
        return existing
        
    candle_dicts = [{'close': float(c.close), 'open': float(c.open), 'high': float(c.high), 'low': float(c.low)} for c in candles]
    
    result = strat.on_candle_closed(candle_dicts)
    
    decision = result.get('decision', 'HOLD')
    reason = result.get('reason', 'no_signal')
    indicator_values = result.get('indicator_values', {})
    
    proposal = None
    if decision in ['BUY', 'SELL']:
        proposal = {
            'action': decision,
            'sizing_intent': 'risk_engine_default'
        }
        
    db_decision = StrategyDecision(
        exchange=request.exchange.lower(),
        symbol=request.symbol,
        timeframe=request.timeframe,
        candle_open_time=latest_candle.open_time,
        strategy_name=strategy_name,
        strategy_version=strat.version,
        configuration=config,
        configuration_hash=config_hash,
        indicator_values=indicator_values,
        decision=decision,
        proposal=proposal,
        reason=reason
    )
    db.add(db_decision)
    db.commit()
    db.refresh(db_decision)
    return db_decision

def get_decisions(db: Session, limit: int = 100):
    return db.execute(select(StrategyDecision).order_by(StrategyDecision.created_at.desc()).limit(limit)).scalars().all()
