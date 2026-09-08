from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import MarketFeatureSnapshot, MarketRegimeSnapshot, ResearchObservation

REGIME_VERSION = "1.0.0"
REGIMES = {"trending_bull", "trending_bear", "ranging", "high_volatility", "low_volatility", "breakout", "mean_reverting", "transition", "unknown"}
DEFAULT_REGIME_CONFIG: dict[str, float] = {
    "min_signal_count": 4,
    "high_volatility": 0.025,
    "low_volatility": 0.004,
    "trend_ma_distance": 0.003,
    "trend_slope": 0.001,
    "momentum": 0.003,
    "breakout_distance": 0.006,
    "breakout_range_percentile": 0.85,
    "breakout_activity": 0.60,
    "range_ma_distance": 0.002,
    "range_slope": 0.0008,
    "mean_revert_rsi_low": 35.0,
    "mean_revert_rsi_high": 65.0,
    "mean_revert_price_distance": 0.010,
    "transition_conflict_score": 2.0,
}


def canonical_regime_configuration_hash(configuration: dict[str, Any]) -> str:
    payload = json.dumps(configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


class RegimeClassifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature_snapshot_id: uuid.UUID
    configuration: dict[str, float] | None = None


class RegimeSnapshotRead(BaseModel):
    id: uuid.UUID
    feature_snapshot_id: uuid.UUID
    observation_event_id: uuid.UUID | None
    exchange: str
    symbol: str
    timeframe: str
    candle_open_time: datetime
    regime: str
    confidence_score: Decimal
    regime_version: str
    configuration: dict[str, Any]
    configuration_hash: str
    supporting_signals: dict[str, Any]
    reason: str
    previous_regime: str | None
    current_regime: str
    changed: bool
    transition_reason: str | None
    created_at: datetime


class MarketRegimeService:
    """Read/research-only deterministic classifier. No exchange, risk, position, or execution dependencies."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def classify(self, request: RegimeClassifyRequest) -> RegimeSnapshotRead:
        feature = self.db.get(MarketFeatureSnapshot, request.feature_snapshot_id)
        if feature is None:
            raise LookupError("Feature snapshot not found")
        config = dict(DEFAULT_REGIME_CONFIG)
        if request.configuration:
            unknown = set(request.configuration) - set(config)
            if unknown:
                raise ValueError(f"Unknown regime configuration keys: {sorted(unknown)}")
            config.update(request.configuration)
        config_hash = canonical_regime_configuration_hash(config)
        existing = self._find_existing(feature.id, config_hash)
        if existing:
            return self._read(existing)

        regime, confidence, signals, reason = self._classify_feature(feature, config)
        previous = self.db.execute(
            select(MarketRegimeSnapshot).where(
                MarketRegimeSnapshot.symbol == feature.symbol,
                MarketRegimeSnapshot.timeframe == feature.timeframe,
                MarketRegimeSnapshot.exchange == feature.exchange,
                MarketRegimeSnapshot.candle_open_time < feature.candle_open_time,
                MarketRegimeSnapshot.regime_version == REGIME_VERSION,
            ).order_by(desc(MarketRegimeSnapshot.candle_open_time), desc(MarketRegimeSnapshot.id)).limit(1)
        ).scalar_one_or_none()
        previous_regime = previous.regime if previous else None
        changed = previous_regime is not None and previous_regime != regime
        transition_reason = f"Regime changed from {previous_regime} to {regime}" if changed else ("Initial regime snapshot" if previous_regime is None else "Regime unchanged")
        signals["transition"] = {"previous_regime": previous_regime, "current_regime": regime, "changed": changed, "transition_reason": transition_reason}

        row = MarketRegimeSnapshot(
            feature_snapshot_id=feature.id, exchange=feature.exchange, symbol=feature.symbol,
            timeframe=feature.timeframe, candle_open_time=feature.candle_open_time,
            regime=regime, confidence_score=Decimal(str(round(confidence, 6))), regime_version=REGIME_VERSION,
            configuration=config, configuration_hash=config_hash, supporting_signals=signals, reason=reason,
            previous_regime=previous_regime, current_regime=regime, changed=changed, transition_reason=transition_reason,
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self._find_existing(feature.id, config_hash)
            if existing:
                return self._read(existing)
            raise
        self.db.refresh(row)
        self._emit_observation(row)
        self.db.refresh(row)
        return self._read(row)

    def get(self, snapshot_id: uuid.UUID) -> RegimeSnapshotRead | None:
        row = self.db.get(MarketRegimeSnapshot, snapshot_id)
        return self._read(row) if row else None

    def list(self, *, symbol: str | None = None, timeframe: str | None = None, regime: str | None = None,
             start: datetime | None = None, end: datetime | None = None, limit: int = 100, offset: int = 0) -> list[RegimeSnapshotRead]:
        stmt = select(MarketRegimeSnapshot)
        if symbol: stmt = stmt.where(MarketRegimeSnapshot.symbol == symbol.upper())
        if timeframe: stmt = stmt.where(MarketRegimeSnapshot.timeframe == timeframe)
        if regime: stmt = stmt.where(MarketRegimeSnapshot.regime == regime)
        if start: stmt = stmt.where(MarketRegimeSnapshot.candle_open_time >= start)
        if end: stmt = stmt.where(MarketRegimeSnapshot.candle_open_time <= end)
        rows = self.db.execute(stmt.order_by(MarketRegimeSnapshot.candle_open_time.asc(), MarketRegimeSnapshot.id.asc()).offset(offset).limit(limit)).scalars().all()
        return [self._read(row) for row in rows]

    def current(self, *, symbol: str, timeframe: str, exchange: str | None = None) -> RegimeSnapshotRead | None:
        stmt = select(MarketRegimeSnapshot).where(MarketRegimeSnapshot.symbol == symbol.upper(), MarketRegimeSnapshot.timeframe == timeframe)
        if exchange: stmt = stmt.where(MarketRegimeSnapshot.exchange == exchange.lower())
        row = self.db.execute(stmt.order_by(desc(MarketRegimeSnapshot.candle_open_time), desc(MarketRegimeSnapshot.id)).limit(1)).scalar_one_or_none()
        return self._read(row) if row else None

    def _find_existing(self, feature_id: uuid.UUID, config_hash: str) -> MarketRegimeSnapshot | None:
        return self.db.execute(select(MarketRegimeSnapshot).where(
            MarketRegimeSnapshot.feature_snapshot_id == feature_id,
            MarketRegimeSnapshot.regime_version == REGIME_VERSION,
            MarketRegimeSnapshot.configuration_hash == config_hash,
        )).scalar_one_or_none()

    def _classify_feature(self, f: MarketFeatureSnapshot, c: dict[str, float]) -> tuple[str, float, dict[str, Any], str]:
        vals = {name: _f(getattr(f, name)) for name in ["volatility","atr","moving_average_distance","moving_average_slope","price_vs_sma_fast","price_vs_sma_slow","price_vs_ema_fast","price_vs_ema_slow","rsi","macd","macd_signal","macd_histogram","momentum","range_percentile","rolling_high_distance","rolling_low_distance","activity","spread_quality","liquidity","rolling_return","return_1"]}
        available = sum(v is not None for v in vals.values())
        signals: dict[str, Any] = {"inputs": vals, "available_signal_count": available}
        if available < int(c["min_signal_count"]):
            return "unknown", 0.0, signals, "Insufficient persisted feature data for deterministic classification"

        vol = vals["volatility"]
        ma = vals["moving_average_distance"]
        slope = vals["moving_average_slope"]
        mom = vals["momentum"]
        hist = vals["macd_histogram"]
        rsi = vals["rsi"]
        rp = vals["range_percentile"]
        hd = vals["rolling_high_distance"]
        ld = vals["rolling_low_distance"]
        activity = vals["activity"]
        pslow = vals["price_vs_sma_slow"]

        scores: dict[str, float] = {}
        if vol is not None:
            scores["high_volatility"] = _clip(vol / c["high_volatility"])
            scores["low_volatility"] = _clip((c["low_volatility"] - vol) / c["low_volatility"]) if vol < c["low_volatility"] else 0.0
        breakout_parts = [
            _clip((rp - c["breakout_range_percentile"]) / max(1e-9, 1-c["breakout_range_percentile"])) if rp is not None else 0,
            _clip((c["breakout_distance"] - min(x for x in [hd, ld] if x is not None)) / c["breakout_distance"]) if any(x is not None for x in [hd,ld]) else 0,
            _clip((activity - c["breakout_activity"]) / max(1e-9, 1-c["breakout_activity"])) if activity is not None else 0,
        ]
        scores["breakout"] = sum(breakout_parts)/3
        bull_parts = [1.0 if ma is not None and ma >= c["trend_ma_distance"] else 0.0, 1.0 if slope is not None and slope >= c["trend_slope"] else 0.0, 1.0 if mom is not None and mom >= c["momentum"] else 0.0, 1.0 if hist is not None and hist > 0 else 0.0, 1.0 if pslow is not None and pslow > 0 else 0.0]
        bear_parts = [1.0 if ma is not None and ma <= -c["trend_ma_distance"] else 0.0, 1.0 if slope is not None and slope <= -c["trend_slope"] else 0.0, 1.0 if mom is not None and mom <= -c["momentum"] else 0.0, 1.0 if hist is not None and hist < 0 else 0.0, 1.0 if pslow is not None and pslow < 0 else 0.0]
        scores["trending_bull"] = sum(bull_parts)/len(bull_parts)
        scores["trending_bear"] = sum(bear_parts)/len(bear_parts)
        range_parts = [1.0 if ma is not None and abs(ma) <= c["range_ma_distance"] else 0.0, 1.0 if slope is not None and abs(slope) <= c["range_slope"] else 0.0, 1.0 if rsi is not None and 40 <= rsi <= 60 else 0.0, 1.0 if mom is not None and abs(mom) <= c["momentum"] else 0.0]
        scores["ranging"] = sum(range_parts)/len(range_parts)
        mr = 0.0
        if rsi is not None and pslow is not None:
            if rsi <= c["mean_revert_rsi_low"] and pslow <= -c["mean_revert_price_distance"]: mr = min(1.0, ((c["mean_revert_rsi_low"]-rsi)/20 + abs(pslow)/c["mean_revert_price_distance"])/2)
            elif rsi >= c["mean_revert_rsi_high"] and pslow >= c["mean_revert_price_distance"]: mr = min(1.0, ((rsi-c["mean_revert_rsi_high"])/20 + abs(pslow)/c["mean_revert_price_distance"])/2)
        scores["mean_reverting"] = mr

        # Priority encodes deterministic semantics for extreme volatility and true breakouts.
        if vol is not None and vol >= c["high_volatility"]: regime = "high_volatility"
        elif vol is not None and vol <= c["low_volatility"] and scores["low_volatility"] > 0: regime = "low_volatility"
        elif scores["breakout"] >= 0.60: regime = "breakout"
        elif scores["trending_bull"] >= 0.60: regime = "trending_bull"
        elif scores["trending_bear"] >= 0.60: regime = "trending_bear"
        elif scores["mean_reverting"] >= 0.55: regime = "mean_reverting"
        elif scores["ranging"] >= 0.50: regime = "ranging"
        else:
            directional = scores["trending_bull"] + scores["trending_bear"] + scores["breakout"] + scores["mean_reverting"]
            regime = "transition" if directional >= c["transition_conflict_score"] else "unknown"
        confidence = _clip(scores.get(regime, 0.35 if regime == "transition" else 0.0))
        signals["scores"] = {k: round(v, 6) for k,v in scores.items()}
        signals["selected_regime"] = regime
        return regime, confidence, signals, f"Deterministic {regime} rule matched with confidence strength {confidence:.3f}"

    def _emit_observation(self, row: MarketRegimeSnapshot) -> None:
        observation = ResearchObservation(
            event_type="market_regime", source="market_regime_engine", exchange=row.exchange,
            symbol=row.symbol, timeframe=row.timeframe, candle_open_time=row.candle_open_time,
            volatility=None, market_context={"regime": row.regime, "confidence": float(row.confidence_score)},
            decision_context={"reason": row.reason, "transition": row.supporting_signals.get("transition")},
            context={"regime_snapshot_id": str(row.id), "feature_snapshot_id": str(row.feature_snapshot_id), "regime_version": row.regime_version, "configuration_hash": row.configuration_hash},
            observed_at=row.candle_open_time,
        )
        self.db.add(observation)
        try:
            self.db.commit(); self.db.refresh(observation)
            row.observation_event_id = observation.event_id
            self.db.commit()
        except Exception:
            self.db.rollback()

    @staticmethod
    def _read(row: MarketRegimeSnapshot) -> RegimeSnapshotRead:
        return RegimeSnapshotRead.model_validate({name: getattr(row, name) for name in RegimeSnapshotRead.model_fields})
