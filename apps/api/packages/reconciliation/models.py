from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReconciliationRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class DiscrepancySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    SEVERE = "severe"


class DiscrepancyStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class ReconciliationRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID = Field(default_factory=uuid4)
    bot_id: str = "demo-bot"
    trigger: str = "startup"
    status: ReconciliationRunStatus = ReconciliationRunStatus.RUNNING
    worker_id: str | None = None
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    discrepancy_count: int = 0
    severe_unresolved_count: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)


class ReconciliationDiscrepancy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    kind: str
    severity: DiscrepancySeverity
    status: DiscrepancyStatus = DiscrepancyStatus.OPEN
    entity_type: str
    entity_id: str
    symbol: str | None = None
    reason_code: str
    local_state: dict[str, Any] = Field(default_factory=dict)
    exchange_state: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


class ExchangePositionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    side: str
    quantity: Decimal


class WorkerLease(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot_id: str
    worker_id: str
    lease_token: UUID = Field(default_factory=uuid4)
    acquired_at: datetime = Field(default_factory=utcnow)
    heartbeat_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime


class LeaseAcquireResult(BaseModel):
    acquired: bool
    lease: WorkerLease | None = None
    reason_code: str | None = None


class ReconciliationStatus(BaseModel):
    latest_run: ReconciliationRun | None = None
    severe_unresolved_count: int = 0
    execution_blocked: bool = False
    active_lease: WorkerLease | None = None
