from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow(): return datetime.now(timezone.utc)


class AlertSeverity(str, Enum):
    INFO='info'; WARNING='warning'; ERROR='error'; CRITICAL='critical'


class IncidentStatus(str, Enum):
    OPEN='open'; RESOLVED='resolved'


class OperationalIncident(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID = Field(default_factory=uuid4)
    incident_key: str
    category: str
    severity: AlertSeverity
    title: str
    status: IncidentStatus = IncidentStatus.OPEN
    context: dict[str, Any] = Field(default_factory=dict)
    occurrence_count: int = 1
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


class OperationalAlert(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID = Field(default_factory=uuid4)
    dedupe_key: str
    category: str
    severity: AlertSeverity
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    emitted_at: datetime = Field(default_factory=utcnow)


class AlertDispatchResult(BaseModel):
    emitted: bool
    alert: OperationalAlert | None = None
    deduplicated: bool = False
    rate_limited: bool = False
    suppressed_count: int = 0
