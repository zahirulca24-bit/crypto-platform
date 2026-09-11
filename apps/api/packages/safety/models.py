from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SafetyScope(str, Enum):
    GLOBAL = "global"
    BOT = "bot"
    SYMBOL = "symbol"
    CIRCUIT = "circuit"


class HaltMode(str, Enum):
    HALTED = "halted"
    PAUSED = "paused"
    DISABLED = "disabled"


class CircuitBreakerType(str, Enum):
    EXCHANGE_CONNECTIVITY = "exchange_connectivity"
    EXCESSIVE_ORDER_ERRORS = "excessive_order_errors"
    RECONCILIATION_FAILURE = "reconciliation_failure"
    DRAWDOWN = "drawdown"
    STALE_MARKET_DATA = "stale_market_data"
    CLOCK_DRIFT = "clock_drift"


class ControlState(BaseModel):
    active: bool = False
    mode: HaltMode = HaltMode.HALTED
    reason_code: str | None = None
    activated_at: datetime | None = None
    activated_by: str | None = None


class CircuitBreakerState(BaseModel):
    breaker: CircuitBreakerType
    open: bool = False
    failure_count: int = 0
    threshold: int = 1
    reason_code: str | None = None
    opened_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_success_at: datetime | None = None
    recovery_observed: bool = False


class SafetyState(BaseModel):
    global_control: ControlState = Field(default_factory=ControlState)
    bots: dict[str, ControlState] = Field(default_factory=dict)
    symbols: dict[str, ControlState] = Field(default_factory=dict)
    circuits: dict[str, CircuitBreakerState] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utcnow)


class SafetyHaltRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=128)
    scope: SafetyScope
    scope_key: str | None = Field(default=None, max_length=128)
    mode: HaltMode = HaltMode.HALTED
    reason_code: str = Field(min_length=1, max_length=96)
    operator_id: str = Field(default="operator", min_length=1, max_length=96)


class SafetyResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=128)
    scope: SafetyScope
    scope_key: str | None = Field(default=None, max_length=128)
    operator_id: str = Field(default="operator", min_length=1, max_length=96)
    acknowledgement: str = Field(min_length=3, max_length=256)


class SafetyCommandResult(BaseModel):
    applied: bool
    idempotent_replay: bool = False
    scope: SafetyScope
    scope_key: str | None = None
    active: bool
    mode: HaltMode | None = None
    reason_code: str | None = None


class SafetyBlocker(BaseModel):
    code: str
    scope: SafetyScope
    scope_key: str | None = None
    reason_code: str | None = None


class SafetyStatus(BaseModel):
    trading_halted: bool
    blockers: list[SafetyBlocker] = Field(default_factory=list)
    state: SafetyState


class CircuitBreakerView(BaseModel):
    breaker: CircuitBreakerType
    open: bool
    failure_count: int
    threshold: int
    reason_code: str | None = None
    opened_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_success_at: datetime | None = None
    recovery_observed: bool = False


class SafetyAuditEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    event_type: str
    scope: SafetyScope | None = None
    scope_key: str | None = None
    reason_code: str | None = None
    operator_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class AutomaticSafetyObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    breaker: CircuitBreakerType
    healthy: bool
    reason_code: str | None = Field(default=None, max_length=96)
