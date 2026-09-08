from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import MarketFeatureSnapshot, OHLCVCandle, ResearchObservation, SymbolSelectionResult, SymbolSelectionRun

FEATURE_VERSION = "1.0.0"
DEFAULT_FEATURE_CONFIG: dict[str, int] = {
    "sma_fast": 10,
    "sma_slow": 20,
    "ema_fast": 12,
    "ema_slow": 26,
    "macd_signal": 9,
    "rsi_period": 14,
    "atr_period": 14,
    "rolling_window": 20,
    "momentum_period": 10,
    "slope_period": 5,
    "history_limit": 300,
}


class FeatureGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exchange: str = Field(min_length=1, max_length=32)
    symbol: str = Field(min_length=1, max_length=64)
    timeframe: str = Field(min_length=1, max_length=16)
    candle_open_time: datetime
    configuration: dict[str, int] | None = None


class FeatureSnapshotRead(BaseModel):
    id: uuid.UUID
    candle_id: uuid.UUID
    observation_event_id: uuid.UUID | None
    exchange: str
    symbol: str
    timeframe: str
    candle_open_time: datetime
    feature_version: str
    configuration: dict[str, int]
    configuration_hash: str
    raw_market: dict[str, Any]
    features: dict[str, Any]
    market_quality: dict[str, Any]
    created_at: datetime


def canonical_configuration_hash(configuration: dict[str, Any]) -> str:
    payload = json.dumps(configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _f(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _dec(value: float | Decimal | None) -> Decimal | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return Decimal(str(value))


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return result


def _rsi(values: list[float], period: int) -> float | None:
    if len(values) < period + 1:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = ((period - 1) * avg_gain + gains[i]) / period
        avg_loss = ((period - 1) * avg_loss + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((x - mean) ** 2 for x in values) / len(values))


def _percentile_rank(values: list[float], target: float) -> float | None:
    if not values:
        return None
    less = sum(1 for value in values if value < target)
    equal = sum(1 for value in values if value == target)
    return (less + 0.5 * equal) / len(values)


class MarketFeatureService:
    """Read-only research feature engine. It never imports or calls exchange/order/risk execution services."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def generate(self, request: FeatureGenerateRequest) -> FeatureSnapshotRead:
        config = dict(DEFAULT_FEATURE_CONFIG)
        if request.configuration:
            unknown = set(request.configuration) - set(DEFAULT_FEATURE_CONFIG)
            if unknown:
                raise ValueError(f"Unknown feature configuration keys: {sorted(unknown)}")
            config.update(request.configuration)
        if any(int(value) <= 0 for value in config.values()):
            raise ValueError("Feature configuration values must be positive integers")
        config_hash = canonical_configuration_hash(config)
        symbol = request.symbol.upper()
        exchange = request.exchange.lower()

        target = self.db.execute(
            select(OHLCVCandle).where(
                OHLCVCandle.exchange == exchange,
                OHLCVCandle.symbol == symbol,
                OHLCVCandle.timeframe == request.timeframe,
                OHLCVCandle.open_time == request.candle_open_time,
                OHLCVCandle.is_closed.is_(True),
            )
        ).scalar_one_or_none()
        if target is None:
            raise LookupError("Closed candle not found")

        existing = self._find_existing(exchange, symbol, request.timeframe, target.open_time, config_hash)
        if existing:
            return self._read(existing)

        candles = list(reversed(self.db.execute(
            select(OHLCVCandle)
            .where(
                OHLCVCandle.exchange == exchange,
                OHLCVCandle.symbol == symbol,
                OHLCVCandle.timeframe == request.timeframe,
                OHLCVCandle.is_closed.is_(True),
                OHLCVCandle.open_time <= target.open_time,
            )
            .order_by(desc(OHLCVCandle.open_time))
            .limit(config["history_limit"])
        ).scalars().all()))
        if not candles or candles[-1].id != target.id:
            raise LookupError("Target candle is outside deterministic history window")

        metrics = self._calculate(candles, config)
        selection = self._selection_context(exchange, symbol, target.open_time)
        observation = self._linked_observation(exchange, symbol, request.timeframe, target.open_time)
        market_quality = self._market_quality(selection, observation)

        row = MarketFeatureSnapshot(
            candle_id=target.id,
            observation_event_id=observation.event_id if observation else None,
            exchange=exchange,
            symbol=symbol,
            timeframe=request.timeframe,
            candle_open_time=target.open_time,
            feature_version=FEATURE_VERSION,
            configuration=config,
            configuration_hash=config_hash,
            selection_context=selection,
            **metrics,
            **market_quality,
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self._find_existing(exchange, symbol, request.timeframe, target.open_time, config_hash)
            if existing:
                return self._read(existing)
            raise
        self.db.refresh(row)
        return self._read(row)

    def get(self, snapshot_id: uuid.UUID) -> FeatureSnapshotRead | None:
        row = self.db.get(MarketFeatureSnapshot, snapshot_id)
        return self._read(row) if row else None

    def list(self, *, symbol: str | None = None, timeframe: str | None = None,
             feature_version: str | None = None, start: datetime | None = None,
             end: datetime | None = None, limit: int = 100, offset: int = 0) -> list[FeatureSnapshotRead]:
        stmt = select(MarketFeatureSnapshot)
        if symbol:
            stmt = stmt.where(MarketFeatureSnapshot.symbol == symbol.upper())
        if timeframe:
            stmt = stmt.where(MarketFeatureSnapshot.timeframe == timeframe)
        if feature_version:
            stmt = stmt.where(MarketFeatureSnapshot.feature_version == feature_version)
        if start:
            stmt = stmt.where(MarketFeatureSnapshot.candle_open_time >= start)
        if end:
            stmt = stmt.where(MarketFeatureSnapshot.candle_open_time <= end)
        rows = self.db.execute(
            stmt.order_by(MarketFeatureSnapshot.candle_open_time.asc(), MarketFeatureSnapshot.id.asc())
            .offset(offset).limit(limit)
        ).scalars().all()
        return [self._read(row) for row in rows]

    def _find_existing(self, exchange: str, symbol: str, timeframe: str,
                       candle_open_time: datetime, config_hash: str) -> MarketFeatureSnapshot | None:
        return self.db.execute(select(MarketFeatureSnapshot).where(
            MarketFeatureSnapshot.exchange == exchange,
            MarketFeatureSnapshot.symbol == symbol,
            MarketFeatureSnapshot.timeframe == timeframe,
            MarketFeatureSnapshot.candle_open_time == candle_open_time,
            MarketFeatureSnapshot.feature_version == FEATURE_VERSION,
            MarketFeatureSnapshot.configuration_hash == config_hash,
        )).scalar_one_or_none()

    def _calculate(self, candles: list[OHLCVCandle], c: dict[str, int]) -> dict[str, Any]:
        closes = [_f(x.close) for x in candles]
        highs = [_f(x.high) for x in candles]
        lows = [_f(x.low) for x in candles]
        volumes = [_f(x.volume) for x in candles]
        opens = [_f(x.open) for x in candles]
        current = candles[-1]
        close = closes[-1]
        prev_close = closes[-2] if len(closes) >= 2 else None
        return_1 = (close / prev_close - 1.0) if prev_close not in (None, 0.0) else None
        log_return = math.log(close / prev_close) if prev_close not in (None, 0.0) and close > 0 else None
        rw = c["rolling_window"]
        rolling_return = (close / closes[-rw] - 1.0) if len(closes) >= rw and closes[-rw] != 0 else None
        rolling_volume = sum(volumes[-rw:]) / rw if len(volumes) >= rw else None
        returns = [(closes[i] / closes[i-1] - 1.0) for i in range(max(1, len(closes)-rw+1), len(closes)) if closes[i-1] != 0]
        volatility = _std(returns)

        tr_values: list[float] = []
        for i, candle in enumerate(candles):
            high, low = highs[i], lows[i]
            if i == 0:
                tr = high - low
            else:
                pc = closes[i-1]
                tr = max(high-low, abs(high-pc), abs(low-pc))
            tr_values.append(tr)
        true_range = tr_values[-1]
        atr = sum(tr_values[-c["atr_period"]:]) / c["atr_period"] if len(tr_values) >= c["atr_period"] else None

        sma_fast = _sma(closes, c["sma_fast"])
        sma_slow = _sma(closes, c["sma_slow"])
        ema_fast_series = _ema_series(closes, c["ema_fast"])
        ema_slow_series = _ema_series(closes, c["ema_slow"])
        ema_fast = ema_fast_series[-1] if len(closes) >= c["ema_fast"] else None
        ema_slow = ema_slow_series[-1] if len(closes) >= c["ema_slow"] else None
        ma_distance = ((sma_fast - sma_slow) / sma_slow) if sma_fast is not None and sma_slow not in (None, 0.0) else None
        slope_period = c["slope_period"]
        fast_smas = [_sma(closes[:i+1], c["sma_fast"]) for i in range(len(closes))]
        slope = None
        if len(fast_smas) > slope_period and fast_smas[-1] is not None and fast_smas[-1-slope_period] not in (None, 0.0):
            slope = (fast_smas[-1] - fast_smas[-1-slope_period]) / abs(fast_smas[-1-slope_period])

        macd_line = [a-b for a,b in zip(ema_fast_series, ema_slow_series)]
        signal_series = _ema_series(macd_line, c["macd_signal"])
        macd = macd_line[-1] if len(closes) >= c["ema_slow"] else None
        macd_signal = signal_series[-1] if macd is not None and len(macd_line) >= c["macd_signal"] else None
        macd_hist = macd - macd_signal if macd is not None and macd_signal is not None else None
        momentum = close / closes[-1-c["momentum_period"]] - 1.0 if len(closes) > c["momentum_period"] and closes[-1-c["momentum_period"]] != 0 else None

        body = abs(close - opens[-1])
        upper_wick = highs[-1] - max(opens[-1], close)
        lower_wick = min(opens[-1], close) - lows[-1]
        candle_range = highs[-1] - lows[-1]
        ranges = [h-l for h,l in zip(highs[-rw:], lows[-rw:])]
        range_percentile = _percentile_rank(ranges, candle_range)
        rolling_high = max(highs[-rw:]) if len(highs) >= rw else None
        rolling_low = min(lows[-rw:]) if len(lows) >= rw else None
        high_distance = (rolling_high - close) / close if rolling_high is not None and close != 0 else None
        low_distance = (close - rolling_low) / close if rolling_low is not None and close != 0 else None

        return {
            "return_1": _dec(return_1), "log_return_1": _dec(log_return),
            "rolling_return": _dec(rolling_return), "rolling_volume": _dec(rolling_volume),
            "volatility": _dec(volatility), "true_range": _dec(true_range), "atr": _dec(atr),
            "sma_fast": _dec(sma_fast), "sma_slow": _dec(sma_slow),
            "ema_fast": _dec(ema_fast), "ema_slow": _dec(ema_slow),
            "moving_average_distance": _dec(ma_distance), "moving_average_slope": _dec(slope),
            "price_vs_sma_fast": _dec((close-sma_fast)/sma_fast if sma_fast not in (None,0.0) else None),
            "price_vs_sma_slow": _dec((close-sma_slow)/sma_slow if sma_slow not in (None,0.0) else None),
            "price_vs_ema_fast": _dec((close-ema_fast)/ema_fast if ema_fast not in (None,0.0) else None),
            "price_vs_ema_slow": _dec((close-ema_slow)/ema_slow if ema_slow not in (None,0.0) else None),
            "rsi": _dec(_rsi(closes, c["rsi_period"])), "macd": _dec(macd),
            "macd_signal": _dec(macd_signal), "macd_histogram": _dec(macd_hist), "momentum": _dec(momentum),
            "candle_body_size": _dec(body), "upper_wick": _dec(upper_wick), "lower_wick": _dec(lower_wick),
            "candle_range": _dec(candle_range), "range_percentile": _dec(range_percentile),
            "rolling_high_distance": _dec(high_distance), "rolling_low_distance": _dec(low_distance),
            "extra_features": {"history_candles_used": len(candles), "latest_source_created_at": current.created_at.isoformat() if current.created_at else None},
        }

    def _selection_context(self, exchange: str, symbol: str, at: datetime) -> dict[str, Any] | None:
        row = self.db.execute(
            select(SymbolSelectionResult, SymbolSelectionRun)
            .join(SymbolSelectionRun, SymbolSelectionResult.run_id == SymbolSelectionRun.id)
            .where(SymbolSelectionRun.exchange == exchange, SymbolSelectionResult.symbol == symbol,
                   SymbolSelectionResult.created_at <= at)
            .order_by(SymbolSelectionResult.created_at.desc(), SymbolSelectionResult.id.desc())
            .limit(1)
        ).first()
        if not row:
            return None
        result, run = row
        return {
            "run_id": str(run.id), "selected": result.selected, "status": "selected" if result.selected else "rejected",
            "score": _f(result.score), "rank": result.rank, "rejection_reasons": result.rejection_reasons or [],
            "raw_metrics": result.raw_metrics or {}, "norm_metrics": result.norm_metrics or {},
            "score_components": result.score_components or {},
        }

    def _linked_observation(self, exchange: str, symbol: str, timeframe: str, at: datetime) -> ResearchObservation | None:
        return self.db.execute(
            select(ResearchObservation).where(
                ResearchObservation.exchange == exchange,
                ResearchObservation.symbol == symbol,
                ResearchObservation.candle_open_time == at,
                ResearchObservation.observed_at <= at,
                (ResearchObservation.timeframe == timeframe) | (ResearchObservation.timeframe.is_(None)),
            ).order_by(ResearchObservation.observed_at.desc(), ResearchObservation.event_id.desc()).limit(1)
        ).scalar_one_or_none()

    def _market_quality(self, selection: dict[str, Any] | None, observation: ResearchObservation | None) -> dict[str, Any]:
        raw = (selection or {}).get("raw_metrics", {})
        norm = (selection or {}).get("norm_metrics", {})
        observed_market = (observation.market_context or {}) if observation else {}
        spread = _f(observation.spread) if observation and observation.spread is not None else raw.get("spread_pct")
        quote_volume = raw.get("quote_volume") or raw.get("quoteVolume") or observed_market.get("quote_volume")
        liquidity = norm.get("liquidity") or norm.get("volume") or observed_market.get("liquidity") or quote_volume
        spread_quality = norm.get("spread_quality") or norm.get("spread") or observed_market.get("spread_quality")
        volatility_suitability = norm.get("volatility_suitability") or norm.get("volatility") or observed_market.get("volatility_suitability")
        activity = norm.get("activity") or norm.get("percent_change") or observed_market.get("activity")
        selection_score = (selection or {}).get("score")
        selection_status = (selection or {}).get("status")
        rejection_reasons = (selection or {}).get("rejection_reasons") or None
        if observation:
            selection_score = selection_score if selection_score is not None else _f(observation.selection_score)
            selection_status = selection_status or observation.selection_status
            rejection_reasons = rejection_reasons or observation.selection_reasons
        return {
            "spread": _dec(spread), "quote_volume": _dec(quote_volume), "liquidity": _dec(liquidity),
            "spread_quality": _dec(spread_quality), "volatility_suitability": _dec(volatility_suitability),
            "activity": _dec(activity), "selection_score": _dec(selection_score),
            "selection_status": selection_status, "rejection_reasons": rejection_reasons,
        }

    def _read(self, row: MarketFeatureSnapshot) -> FeatureSnapshotRead:
        candle = self.db.get(OHLCVCandle, row.candle_id)
        feature_names = [
            "return_1","log_return_1","rolling_return","rolling_volume","volatility","true_range","atr",
            "sma_fast","sma_slow","ema_fast","ema_slow","moving_average_distance","moving_average_slope",
            "price_vs_sma_fast","price_vs_sma_slow","price_vs_ema_fast","price_vs_ema_slow",
            "rsi","macd","macd_signal","macd_histogram","momentum","candle_body_size","upper_wick","lower_wick",
            "candle_range","range_percentile","rolling_high_distance","rolling_low_distance",
        ]
        features = {name: getattr(row, name) for name in feature_names}
        if row.extra_features:
            features.update(row.extra_features)
        return FeatureSnapshotRead(
            id=row.id, candle_id=row.candle_id, observation_event_id=row.observation_event_id,
            exchange=row.exchange, symbol=row.symbol, timeframe=row.timeframe, candle_open_time=row.candle_open_time,
            feature_version=row.feature_version, configuration=row.configuration, configuration_hash=row.configuration_hash,
            raw_market={
                "open": candle.open, "high": candle.high, "low": candle.low, "close": candle.close,
                "volume": candle.volume, "spread": row.spread, "quote_volume": row.quote_volume,
            },
            features=features,
            market_quality={
                "liquidity": row.liquidity, "spread_quality": row.spread_quality,
                "volatility_suitability": row.volatility_suitability, "activity": row.activity,
                "selection_score": row.selection_score, "selection_status": row.selection_status,
                "rejection_reasons": row.rejection_reasons, "selection_context": row.selection_context,
            },
            created_at=row.created_at,
        )
