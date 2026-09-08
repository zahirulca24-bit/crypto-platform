from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import ResearchObservation
from .models import ObservationCreate, ObservationRead, ResearchSummary

logger = logging.getLogger(__name__)
ZERO = Decimal("0")


class ResearchObservationService:
    """Persistence/read service only; it has no exchange, credential, risk-bypass, or order APIs."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record(self, observation: ObservationCreate) -> ObservationRead:
        values = observation.model_dump(exclude_none=True)
        row = ResearchObservation(**values)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self._read(row)

    def get(self, event_id: UUID | str) -> ObservationRead | None:
        try:
            event_uuid = event_id if isinstance(event_id, UUID) else UUID(str(event_id))
        except ValueError:
            return None
        row = self.db.execute(
            select(ResearchObservation).where(ResearchObservation.event_id == event_uuid)
        ).scalar_one_or_none()
        return self._read(row) if row else None

    def list(
        self,
        *,
        event_type: str | None = None,
        symbol: str | None = None,
        strategy: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ObservationRead]:
        stmt = select(ResearchObservation)
        if event_type:
            stmt = stmt.where(ResearchObservation.event_type == event_type)
        if symbol:
            stmt = stmt.where(ResearchObservation.symbol == symbol.upper())
        if strategy:
            stmt = stmt.where(ResearchObservation.strategy_name == strategy)
        if start:
            stmt = stmt.where(ResearchObservation.observed_at >= start)
        if end:
            stmt = stmt.where(ResearchObservation.observed_at <= end)
        stmt = stmt.order_by(ResearchObservation.observed_at.desc(), ResearchObservation.event_id.desc())
        rows = self.db.execute(stmt.offset(offset).limit(limit)).scalars().all()
        return [self._read(row) for row in rows]

    def summary(self, *, start: datetime | None = None, end: datetime | None = None) -> ResearchSummary:
        filters = []
        if start:
            filters.append(ResearchObservation.observed_at >= start)
        if end:
            filters.append(ResearchObservation.observed_at <= end)

        total = self.db.execute(select(func.count()).select_from(ResearchObservation).where(*filters)).scalar_one()
        event_rows = self.db.execute(
            select(ResearchObservation.event_type, func.count())
            .where(*filters)
            .group_by(ResearchObservation.event_type)
            .order_by(ResearchObservation.event_type)
        ).all()
        selection_rows = self.db.execute(
            select(ResearchObservation.selection_status, func.count())
            .where(*filters, ResearchObservation.selection_status.is_not(None))
            .group_by(ResearchObservation.selection_status)
            .order_by(ResearchObservation.selection_status)
        ).all()
        realized, fees, slippage = self.db.execute(
            select(
                func.coalesce(func.sum(ResearchObservation.realized_pnl), 0),
                func.coalesce(func.sum(ResearchObservation.fees), 0),
                func.coalesce(func.sum(ResearchObservation.slippage), 0),
            ).where(*filters)
        ).one()
        return ResearchSummary(
            total_observations=total,
            by_event_type={name: count for name, count in event_rows},
            by_selection_status={name: count for name, count in selection_rows},
            realized_pnl=Decimal(str(realized or 0)),
            fees=Decimal(str(fees or 0)),
            slippage=Decimal(str(slippage or 0)),
        )

    @staticmethod
    def _read(row: ResearchObservation) -> ObservationRead:
        fields = ObservationRead.model_fields.keys()
        return ObservationRead.model_validate({name: getattr(row, name) for name in fields})


def observe_best_effort(db: Session, observation: ObservationCreate) -> None:
    """Append an observation without allowing telemetry failure to block authoritative trading flow."""
    try:
        ResearchObservationService(db).record(observation)
    except Exception:
        db.rollback()
        logger.exception("R&D observation persistence failed for %s", observation.event_type)
