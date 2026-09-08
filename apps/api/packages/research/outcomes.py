from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import (
    AppliedOrderFillModel,
    DemoOrderModel,
    MarketFeatureSnapshot,
    MarketRegimeSnapshot,
    OHLCVCandle,
    PositionModel,
    PositionProtectionModel,
    ResearchObservation,
    RiskDecisionModel,
    TradeOutcome,
)
from packages.exchange.models import DemoOrder
from packages.positions.models import Position
from packages.protection.models import PositionProtection
from packages.risk.models import RiskDecision

OUTCOME_VERSION = "1.0.0"
EXIT_REASONS = {"take_profit", "stop_loss", "strategy_exit", "manual", "reconciliation", "unknown"}
ZERO = Decimal("0")
HUNDRED = Decimal("100")


class OutcomeGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_id: uuid.UUID
    exchange: str = "demo"
    timeframe: str | None = None
    bot_id: str | None = None
    strategy_name: str = Field(min_length=1, max_length=64)
    strategy_version: str = "unknown"
    strategy_config_hash: str = "unknown"
    exit_reason: str | None = None


class TradeOutcomeRead(BaseModel):
    id: uuid.UUID
    source_position_id: uuid.UUID
    observation_event_id: uuid.UUID | None
    exchange: str
    symbol: str
    timeframe: str | None
    bot_id: str | None
    strategy_name: str
    strategy_version: str
    strategy_config_hash: str
    side: str
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    notional: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    fees: Decimal
    slippage: Decimal
    holding_time_seconds: Decimal
    exit_reason: str
    tp_price: Decimal | None
    sl_price: Decimal | None
    mae: Decimal
    mfe: Decimal
    return_pct: Decimal
    risk_amount: Decimal | None
    r_multiple: Decimal | None
    regime_at_entry: str | None
    regime_at_exit: str | None
    entry_feature_snapshot_id: uuid.UUID | None
    exit_feature_snapshot_id: uuid.UUID | None
    entry_regime_snapshot_id: uuid.UUID | None
    exit_regime_snapshot_id: uuid.UUID | None
    outcome_version: str
    context: dict[str, Any]
    created_at: datetime


class PerformanceRow(BaseModel):
    group_by: str
    group_value: str
    trade_count: int
    wins: int
    losses: int
    win_rate: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    average_win: Decimal
    average_loss: Decimal
    profit_factor: Decimal | None
    expectancy: Decimal
    average_r_multiple: Decimal | None
    average_holding_time: Decimal
    average_mae: Decimal
    average_mfe: Decimal
    fees_total: Decimal
    slippage_total: Decimal
    max_drawdown: Decimal


def _d(value: Any) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)


class TradeOutcomeService:
    """Research-only trade reconstruction and analytics. Has no execution dependencies."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def generate(self, request: OutcomeGenerateRequest) -> TradeOutcomeRead:
        existing = self.db.execute(select(TradeOutcome).where(
            TradeOutcome.source_position_id == request.position_id,
            TradeOutcome.outcome_version == OUTCOME_VERSION,
        )).scalar_one_or_none()
        if existing:
            return self._read(existing)

        position_row = self.db.get(PositionModel, request.position_id)
        if position_row is None:
            raise LookupError("Position not found")
        position = Position.model_validate(position_row.position_json)
        if position.status.value != "closed":
            raise ValueError("Trade outcome can only be generated for a closed authoritative position")

        fills = self._orders_for_position(request.position_id)
        if len(fills) < 2:
            raise ValueError("Closed position does not have enough persisted fills to reconstruct an outcome")

        entry = fills[0]
        exit_order = fills[-1]
        entry_time = entry.created_at
        exit_time = exit_order.updated_at or exit_order.created_at
        if exit_time < entry_time:
            raise ValueError("Exit time precedes entry time")

        entry_side = entry.side.upper()
        exit_side = "SELL" if entry_side == "BUY" else "BUY"
        entry_fills = [x for x in fills if x.side.upper() == entry_side]
        exit_fills = [x for x in fills if x.side.upper() == exit_side]
        entry_quantity = sum((_d(x.filled_quantity) for x in entry_fills), ZERO)
        exit_quantity = sum((_d(x.filled_quantity) for x in exit_fills), ZERO)
        quantity = min(entry_quantity, exit_quantity)
        if quantity <= ZERO or not exit_fills:
            raise ValueError("Reconstructed trade quantity must be positive")
        entry_price = _d(position.average_entry_price)
        exit_price = sum((_d(x.price) * _d(x.filled_quantity) for x in exit_fills), ZERO) / exit_quantity
        side = "long" if entry_side == "BUY" else "short"
        direction = Decimal("1") if side == "long" else Decimal("-1")
        notional = entry_price * quantity
        gross_pnl = (exit_price - entry_price) * quantity * direction
        fees = sum((_d(x.fee) for x in fills), ZERO)
        slippage = self._slippage_for_orders(fills)
        net_pnl = gross_pnl - fees - slippage
        holding = Decimal(str((exit_time - entry_time).total_seconds()))
        return_pct = (gross_pnl / notional * HUNDRED) if notional else ZERO

        protection = self._protection(request.position_id)
        tp_price = _d(protection.tp_price) if protection else None
        sl_price = _d(protection.sl_price) if protection else None
        exit_reason = self._resolve_exit_reason(request.exit_reason, exit_price, tp_price, sl_price, side)
        risk_amount = self._risk_amount(entry.risk_decision_id)
        r_multiple = (net_pnl / risk_amount) if risk_amount is not None and risk_amount > ZERO else None

        entry_feature = self._feature_at(request.exchange, position.symbol, request.timeframe, entry_time)
        exit_feature = self._feature_at(request.exchange, position.symbol, request.timeframe, exit_time)
        entry_regime = self._regime_at(request.exchange, position.symbol, request.timeframe, entry_time)
        exit_regime = self._regime_at(request.exchange, position.symbol, request.timeframe, exit_time)
        mae, mfe, candle_count = self._excursions(request.exchange, position.symbol, request.timeframe, entry_time, exit_time, entry_price, quantity, side)

        row = TradeOutcome(
            source_position_id=request.position_id,
            exchange=request.exchange.lower(), symbol=position.symbol.upper(), timeframe=request.timeframe,
            bot_id=request.bot_id, strategy_name=request.strategy_name, strategy_version=request.strategy_version,
            strategy_config_hash=request.strategy_config_hash, side=side,
            entry_time=entry_time, exit_time=exit_time, entry_price=_q(entry_price), exit_price=_q(exit_price),
            quantity=_q(quantity), notional=_q(notional), gross_pnl=_q(gross_pnl), net_pnl=_q(net_pnl),
            fees=_q(fees), slippage=_q(slippage), holding_time_seconds=holding,
            exit_reason=exit_reason, tp_price=_q(tp_price) if tp_price is not None else None,
            sl_price=_q(sl_price) if sl_price is not None else None, mae=_q(mae), mfe=_q(mfe),
            return_pct=_q(return_pct), risk_amount=_q(risk_amount) if risk_amount is not None else None,
            r_multiple=_q(r_multiple) if r_multiple is not None else None,
            regime_at_entry=entry_regime.regime if entry_regime else None,
            regime_at_exit=exit_regime.regime if exit_regime else None,
            entry_feature_snapshot_id=entry_feature.id if entry_feature else None,
            exit_feature_snapshot_id=exit_feature.id if exit_feature else None,
            entry_regime_snapshot_id=entry_regime.id if entry_regime else None,
            exit_regime_snapshot_id=exit_regime.id if exit_regime else None,
            outcome_version=OUTCOME_VERSION,
            context={
                "source": "authoritative_phase2_reconstruction",
                "fill_order_ids": [str(x.id) for x in fills],
                "mae_mfe_closed_candle_count": candle_count,
                "mae_mfe_definition": "absolute PnL excursion from entry using closed candles only",
                "slippage_source": "research_observations",
            },
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.execute(select(TradeOutcome).where(
                TradeOutcome.source_position_id == request.position_id,
                TradeOutcome.outcome_version == OUTCOME_VERSION,
            )).scalar_one_or_none()
            if existing:
                return self._read(existing)
            raise
        self.db.refresh(row)
        self._emit_observation(row)
        self.db.refresh(row)
        return self._read(row)

    def get(self, outcome_id: uuid.UUID) -> TradeOutcomeRead | None:
        row = self.db.get(TradeOutcome, outcome_id)
        return self._read(row) if row else None

    def list(self, *, symbol: str | None = None, strategy: str | None = None, regime: str | None = None,
             timeframe: str | None = None, start: datetime | None = None, end: datetime | None = None,
             exit_reason: str | None = None, limit: int = 100, offset: int = 0) -> list[TradeOutcomeRead]:
        stmt = self._filtered_stmt(symbol=symbol, strategy=strategy, regime=regime, timeframe=timeframe,
                                   start=start, end=end, exit_reason=exit_reason)
        rows = self.db.execute(stmt.order_by(TradeOutcome.entry_time.asc(), TradeOutcome.id.asc()).offset(offset).limit(limit)).scalars().all()
        return [self._read(row) for row in rows]

    def performance(self, *, group_by: Literal["symbol", "strategy", "strategy_version", "regime", "timeframe", "exit_reason"] = "symbol",
                    symbol: str | None = None, strategy: str | None = None, regime: str | None = None,
                    timeframe: str | None = None, start: datetime | None = None, end: datetime | None = None,
                    exit_reason: str | None = None) -> list[PerformanceRow]:
        rows = self.db.execute(self._filtered_stmt(symbol=symbol, strategy=strategy, regime=regime, timeframe=timeframe,
                                                   start=start, end=end, exit_reason=exit_reason)
                               .order_by(TradeOutcome.exit_time.asc(), TradeOutcome.id.asc())).scalars().all()
        attr = {"strategy": "strategy_name", "regime": "regime_at_entry"}.get(group_by, group_by)
        buckets: dict[str, list[TradeOutcome]] = {}
        for row in rows:
            value = getattr(row, attr)
            key = str(value) if value is not None else "unknown"
            buckets.setdefault(key, []).append(row)
        return [self._aggregate(group_by, key, values) for key, values in sorted(buckets.items())]

    def _filtered_stmt(self, **filters):
        stmt = select(TradeOutcome)
        if filters.get("symbol"): stmt = stmt.where(TradeOutcome.symbol == filters["symbol"].upper())
        if filters.get("strategy"): stmt = stmt.where(TradeOutcome.strategy_name == filters["strategy"])
        if filters.get("regime"): stmt = stmt.where(TradeOutcome.regime_at_entry == filters["regime"])
        if filters.get("timeframe"): stmt = stmt.where(TradeOutcome.timeframe == filters["timeframe"])
        if filters.get("start"): stmt = stmt.where(TradeOutcome.entry_time >= filters["start"])
        if filters.get("end"): stmt = stmt.where(TradeOutcome.exit_time <= filters["end"])
        if filters.get("exit_reason"): stmt = stmt.where(TradeOutcome.exit_reason == filters["exit_reason"])
        return stmt

    def _orders_for_position(self, position_id: uuid.UUID) -> list[DemoOrder]:
        rows = self.db.execute(
            select(DemoOrderModel).join(AppliedOrderFillModel, AppliedOrderFillModel.order_id == DemoOrderModel.id)
            .where(AppliedOrderFillModel.position_id == position_id)
            .order_by(DemoOrderModel.created_at.asc(), DemoOrderModel.id.asc())
        ).scalars().all()
        return [DemoOrder.model_validate(row.order_json) for row in rows]

    def _slippage_for_orders(self, orders: list[DemoOrder]) -> Decimal:
        ids = {str(x.id) for x in orders}
        rows = self.db.execute(select(ResearchObservation).where(
            ResearchObservation.event_type.in_(["order.filled", "trade.completed", "trade_outcome"]),
            ResearchObservation.slippage.is_not(None),
        )).scalars().all()
        total = ZERO
        for row in rows:
            ctx = row.trade_context or {}
            if str(ctx.get("order_id", "")) in ids:
                total += _d(row.slippage)
        return total

    def _risk_amount(self, risk_decision_id: uuid.UUID) -> Decimal | None:
        row = self.db.get(RiskDecisionModel, risk_decision_id)
        if not row: return None
        decision = RiskDecision.model_validate(row.decision_json)
        return _d(decision.risk_amount) if decision.risk_amount is not None else None

    def _protection(self, position_id: uuid.UUID) -> PositionProtection | None:
        row = self.db.get(PositionProtectionModel, position_id)
        return PositionProtection.model_validate(row.protection_json) if row else None

    @staticmethod
    def _resolve_exit_reason(explicit: str | None, exit_price: Decimal, tp: Decimal | None, sl: Decimal | None, side: str) -> str:
        if explicit is not None:
            if explicit not in EXIT_REASONS: raise ValueError(f"Unsupported exit_reason: {explicit}")
            return explicit
        if tp is not None and ((side == "long" and exit_price >= tp) or (side == "short" and exit_price <= tp)):
            return "take_profit"
        if sl is not None and ((side == "long" and exit_price <= sl) or (side == "short" and exit_price >= sl)):
            return "stop_loss"
        return "unknown"

    def _feature_at(self, exchange: str, symbol: str, timeframe: str | None, at: datetime):
        if timeframe is None: return None
        return self.db.execute(select(MarketFeatureSnapshot).where(
            MarketFeatureSnapshot.exchange == exchange.lower(), MarketFeatureSnapshot.symbol == symbol.upper(),
            MarketFeatureSnapshot.timeframe == timeframe, MarketFeatureSnapshot.candle_open_time <= at,
        ).order_by(desc(MarketFeatureSnapshot.candle_open_time), desc(MarketFeatureSnapshot.id)).limit(1)).scalar_one_or_none()

    def _regime_at(self, exchange: str, symbol: str, timeframe: str | None, at: datetime):
        if timeframe is None: return None
        return self.db.execute(select(MarketRegimeSnapshot).where(
            MarketRegimeSnapshot.exchange == exchange.lower(), MarketRegimeSnapshot.symbol == symbol.upper(),
            MarketRegimeSnapshot.timeframe == timeframe, MarketRegimeSnapshot.candle_open_time <= at,
        ).order_by(desc(MarketRegimeSnapshot.candle_open_time), desc(MarketRegimeSnapshot.id)).limit(1)).scalar_one_or_none()

    def _excursions(self, exchange: str, symbol: str, timeframe: str | None, entry_time: datetime, exit_time: datetime,
                    entry_price: Decimal, quantity: Decimal, side: str) -> tuple[Decimal, Decimal, int]:
        if timeframe is None: return ZERO, ZERO, 0
        candles = self.db.execute(select(OHLCVCandle).where(
            OHLCVCandle.exchange == exchange.lower(), OHLCVCandle.symbol == symbol.upper(), OHLCVCandle.timeframe == timeframe,
            OHLCVCandle.is_closed.is_(True), OHLCVCandle.open_time >= entry_time, OHLCVCandle.open_time <= exit_time,
        ).order_by(OHLCVCandle.open_time.asc())).scalars().all()
        if not candles: return ZERO, ZERO, 0
        if side == "long":
            adverse = min((_d(c.low) - entry_price) * quantity for c in candles)
            favorable = max((_d(c.high) - entry_price) * quantity for c in candles)
        else:
            adverse = min((entry_price - _d(c.high)) * quantity for c in candles)
            favorable = max((entry_price - _d(c.low)) * quantity for c in candles)
        return max(ZERO, -adverse), max(ZERO, favorable), len(candles)

    def _emit_observation(self, row: TradeOutcome) -> None:
        observation = ResearchObservation(
            event_type="trade_outcome", source="trade_outcome_engine", exchange=row.exchange, symbol=row.symbol,
            timeframe=row.timeframe, bot_id=row.bot_id, strategy_name=row.strategy_name,
            strategy_version=row.strategy_version, strategy_config_hash=row.strategy_config_hash,
            side=row.side, entry_price=row.entry_price, exit_price=row.exit_price, quantity=row.quantity,
            notional=row.notional, take_profit=row.tp_price, stop_loss=row.sl_price, fees=row.fees,
            slippage=row.slippage, realized_pnl=row.net_pnl, holding_time_seconds=row.holding_time_seconds,
            exit_reason=row.exit_reason, mae=row.mae, mfe=row.mfe,
            trade_context={"return_pct": str(row.return_pct), "r_multiple": str(row.r_multiple) if row.r_multiple is not None else None,
                           "regime_at_entry": row.regime_at_entry, "regime_at_exit": row.regime_at_exit},
            context={"trade_outcome_id": str(row.id), "source_position_id": str(row.source_position_id), "outcome_version": row.outcome_version},
            observed_at=row.exit_time,
        )
        self.db.add(observation)
        try:
            self.db.commit(); self.db.refresh(observation)
            row.observation_event_id = observation.event_id
            self.db.commit()
        except Exception:
            self.db.rollback()

    @staticmethod
    def _aggregate(group_by: str, key: str, rows: list[TradeOutcome]) -> PerformanceRow:
        count = len(rows)
        wins = [r for r in rows if _d(r.net_pnl) > ZERO]
        losses = [r for r in rows if _d(r.net_pnl) < ZERO]
        gross_profit = sum((_d(r.net_pnl) for r in wins), ZERO)
        gross_loss_abs = sum((-_d(r.net_pnl) for r in losses), ZERO)
        net = sum((_d(r.net_pnl) for r in rows), ZERO)
        cumulative = ZERO; peak = ZERO; max_dd = ZERO
        for r in rows:
            cumulative += _d(r.net_pnl); peak = max(peak, cumulative); max_dd = max(max_dd, peak - cumulative)
        rvals = [_d(r.r_multiple) for r in rows if r.r_multiple is not None]
        return PerformanceRow(
            group_by=group_by, group_value=key, trade_count=count, wins=len(wins), losses=len(losses),
            win_rate=_q(Decimal(len(wins)) / Decimal(count) if count else ZERO),
            gross_pnl=_q(sum((_d(r.gross_pnl) for r in rows), ZERO)), net_pnl=_q(net),
            average_win=_q(gross_profit / Decimal(len(wins)) if wins else ZERO),
            average_loss=_q(-gross_loss_abs / Decimal(len(losses)) if losses else ZERO),
            profit_factor=_q(gross_profit / gross_loss_abs) if gross_loss_abs > ZERO else None,
            expectancy=_q(net / Decimal(count) if count else ZERO),
            average_r_multiple=_q(sum(rvals, ZERO) / Decimal(len(rvals))) if rvals else None,
            average_holding_time=_q(sum((_d(r.holding_time_seconds) for r in rows), ZERO) / Decimal(count)),
            average_mae=_q(sum((_d(r.mae) for r in rows), ZERO) / Decimal(count)),
            average_mfe=_q(sum((_d(r.mfe) for r in rows), ZERO) / Decimal(count)),
            fees_total=_q(sum((_d(r.fees) for r in rows), ZERO)), slippage_total=_q(sum((_d(r.slippage) for r in rows), ZERO)),
            max_drawdown=_q(max_dd),
        )

    @staticmethod
    def _read(row: TradeOutcome) -> TradeOutcomeRead:
        return TradeOutcomeRead.model_validate({name: getattr(row, name) for name in TradeOutcomeRead.model_fields})
