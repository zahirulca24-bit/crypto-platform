"""Domain models for deterministic, execution-free risk evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


DecimalValue = Annotated[Decimal, Field(max_digits=30, decimal_places=12)]


class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class StrategyOrderProposal(BaseModel):
    """An intent from a strategy.  Deliberately has no quantity field."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    symbol: str = Field(min_length=1, max_length=32)
    action: OrderAction
    price: Decimal
    stop_price: Decimal | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class PositionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    quantity: Decimal
    mark_price: Decimal


class PortfolioSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available_balance: Decimal
    daily_pnl: Decimal = Decimal("0")
    peak_equity: Decimal | None = None
    current_equity: Decimal | None = None
    positions: list[PositionSnapshot] = Field(default_factory=list)


class RiskPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_risk_per_trade: Decimal = Decimal("100")
    max_position_notional: Decimal = Decimal("1000")
    max_total_portfolio_exposure: Decimal = Decimal("5000")
    max_open_positions: int = Field(default=10, ge=0)
    max_exposure_per_symbol: Decimal = Decimal("1000")
    max_daily_loss: Decimal = Decimal("500")
    max_drawdown: Decimal = Decimal("1000")
    minimum_available_balance: Decimal = Decimal("50")
    minimum_trade_quantity: Decimal = Decimal("0.00000001")


class RiskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    proposal: StrategyOrderProposal
    approved: bool
    approved_quantity: Decimal | None = None
    approved_notional: Decimal | None = None
    risk_amount: Decimal | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    policy_snapshot: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RiskEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal: StrategyOrderProposal
    portfolio: PortfolioSnapshot
    policy: RiskPolicy = Field(default_factory=RiskPolicy)
