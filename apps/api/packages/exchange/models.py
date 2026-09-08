"""Demo order domain models.  These models intentionally contain no live exchange credentials."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTING = "submitting"
    OPEN = "open"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class DemoOrderSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_decision_id: UUID
    type: OrderType = OrderType.LIMIT


class DemoOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    risk_decision_id: UUID
    client_order_id: str
    exchange_order_id: str | None = None
    symbol: str
    side: str
    type: OrderType
    quantity: Decimal
    price: Decimal
    filled_quantity: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")
    status: OrderStatus = OrderStatus.PENDING
    raw_exchange_response: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
