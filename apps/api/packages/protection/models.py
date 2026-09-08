from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProtectionStatus(str, Enum):
    PROTECTED = "protected"
    PARTIAL = "partial"
    MISSING = "missing"
    ERROR = "error"
    NOT_REQUIRED = "not_required"


class ProtectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_id: UUID
    tp_price: Decimal
    sl_price: Decimal


class PositionProtection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_id: UUID
    tp_price: Decimal
    sl_price: Decimal
    tp_order_id: str | None = None
    sl_order_id: str | None = None
    protection_status: ProtectionStatus
    last_verified_at: datetime | None = None
    error_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
