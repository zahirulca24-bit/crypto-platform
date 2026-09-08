"""Decimal-only state models for authoritative position accounting."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    symbol: str
    side: PositionSide
    quantity: Decimal
    average_entry_price: Decimal
    current_price: Decimal
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: PositionStatus = PositionStatus.OPEN


class PortfolioSummary(BaseModel):
    open_positions: int
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    fees: Decimal
    net_pnl: Decimal
