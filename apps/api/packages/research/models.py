from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID | None = None
    event_type: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=64)
    exchange: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    bot_id: str | None = None
    strategy_name: str | None = None
    strategy_version: str | None = None
    strategy_config_hash: str | None = None
    candle_open_time: datetime | None = None

    price: Decimal | None = None
    volume: Decimal | None = None
    spread: Decimal | None = None
    volatility: Decimal | None = None
    indicator_values: dict[str, Any] | None = None
    selection_score: Decimal | None = None
    selection_status: str | None = None
    selection_reasons: list[str] | None = None

    side: str | None = None
    entry_price: Decimal | None = None
    exit_price: Decimal | None = None
    quantity: Decimal | None = None
    notional: Decimal | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    fees: Decimal | None = None
    slippage: Decimal | None = None
    realized_pnl: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    holding_time_seconds: Decimal | None = None
    exit_reason: str | None = None
    mae: Decimal | None = None
    mfe: Decimal | None = None

    strategy_decision: str | None = None
    strategy_reason: str | None = None
    risk_approved: bool | None = None
    risk_rejection_reasons: list[str] | None = None
    order_status: str | None = None
    protection_status: str | None = None
    reconciliation_context: dict[str, Any] | None = None
    error_context: dict[str, Any] | None = None
    market_context: dict[str, Any] | None = None
    trade_context: dict[str, Any] | None = None
    decision_context: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    observed_at: datetime | None = None


class ObservationRead(ObservationCreate):
    event_id: UUID
    observed_at: datetime


class ResearchSummary(BaseModel):
    total_observations: int
    by_event_type: dict[str, int]
    by_selection_status: dict[str, int]
    realized_pnl: Decimal
    fees: Decimal
    slippage: Decimal
