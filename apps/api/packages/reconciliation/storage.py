from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from models import ReconciliationDiscrepancyModel, ReconciliationRunModel, WorkerLeaseModel
from .models import DiscrepancyStatus, ReconciliationDiscrepancy, ReconciliationRun, WorkerLease


class ReconciliationStore:
    def __init__(self, db):
        self.db = db

    def create_run(self, run: ReconciliationRun) -> ReconciliationRun:
        self.db.add(ReconciliationRunModel(
            id=run.id, bot_id=run.bot_id, status=run.status.value,
            run_json=run.model_dump(mode="json"), started_at=run.started_at,
            completed_at=run.completed_at,
        ))
        self.db.commit()
        return run

    def save_run(self, run: ReconciliationRun) -> ReconciliationRun:
        row = self.db.execute(select(ReconciliationRunModel).where(ReconciliationRunModel.id == run.id)).scalar_one()
        row.status = run.status.value
        row.run_json = run.model_dump(mode="json")
        row.completed_at = run.completed_at
        self.db.commit()
        return run

    def latest_run(self, bot_id: str = "demo-bot") -> ReconciliationRun | None:
        row = self.db.execute(
            select(ReconciliationRunModel).where(ReconciliationRunModel.bot_id == bot_id)
            .order_by(ReconciliationRunModel.started_at.desc()).limit(1)
        ).scalar_one_or_none()
        return ReconciliationRun.model_validate(row.run_json) if row else None

    def runs(self, limit: int = 100, offset: int = 0) -> list[ReconciliationRun]:
        rows = self.db.execute(select(ReconciliationRunModel).order_by(ReconciliationRunModel.started_at.desc()).offset(offset).limit(limit)).scalars().all()
        return [ReconciliationRun.model_validate(r.run_json) for r in rows]

    def add_discrepancy(self, discrepancy: ReconciliationDiscrepancy) -> ReconciliationDiscrepancy:
        self.db.add(ReconciliationDiscrepancyModel(
            id=discrepancy.id, run_id=discrepancy.run_id, severity=discrepancy.severity.value,
            status=discrepancy.status.value, kind=discrepancy.kind,
            discrepancy_json=discrepancy.model_dump(mode="json"), detected_at=discrepancy.detected_at,
            resolved_at=discrepancy.resolved_at,
        ))
        self.db.commit()
        return discrepancy

    def discrepancies(self, *, run_id: UUID | str | None = None, unresolved_only: bool = False, limit: int = 200, offset: int = 0) -> list[ReconciliationDiscrepancy]:
        stmt = select(ReconciliationDiscrepancyModel)
        if run_id is not None:
            stmt = stmt.where(ReconciliationDiscrepancyModel.run_id == str(run_id))
        if unresolved_only:
            stmt = stmt.where(ReconciliationDiscrepancyModel.status == "open")
        rows = self.db.execute(stmt.order_by(ReconciliationDiscrepancyModel.detected_at.desc()).offset(offset).limit(limit)).scalars().all()
        return [ReconciliationDiscrepancy.model_validate(r.discrepancy_json) for r in rows]

    def severe_unresolved_count(self) -> int:
        rows = self.db.execute(select(ReconciliationDiscrepancyModel).where(
            ReconciliationDiscrepancyModel.status == "open",
            ReconciliationDiscrepancyModel.severity == "severe",
        )).scalars().all()
        return len(rows)

    def resolve_open_severe(self) -> int:
        now = datetime.now(timezone.utc)
        rows = self.db.execute(select(ReconciliationDiscrepancyModel).where(
            ReconciliationDiscrepancyModel.status == "open",
            ReconciliationDiscrepancyModel.severity == "severe",
        )).scalars().all()
        for row in rows:
            d = ReconciliationDiscrepancy.model_validate(row.discrepancy_json)
            d.status = DiscrepancyStatus.RESOLVED
            d.resolved_at = now
            row.status = "resolved"
            row.resolved_at = now
            row.discrepancy_json = d.model_dump(mode="json")
        self.db.commit()
        return len(rows)

    @contextmanager
    def locked_lease(self, bot_id: str):
        row = self.db.execute(select(WorkerLeaseModel).where(WorkerLeaseModel.bot_id == bot_id).with_for_update()).scalar_one_or_none()
        try:
            yield row
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def load_lease(self, bot_id: str) -> WorkerLease | None:
        row = self.db.execute(select(WorkerLeaseModel).where(WorkerLeaseModel.bot_id == bot_id)).scalar_one_or_none()
        return WorkerLease.model_validate(row.lease_json) if row else None

    def create_lease(self, lease: WorkerLease) -> WorkerLease | None:
        stmt = insert(WorkerLeaseModel).values(
            bot_id=lease.bot_id, worker_id=lease.worker_id, lease_token=lease.lease_token,
            lease_json=lease.model_dump(mode="json"), heartbeat_at=lease.heartbeat_at, expires_at=lease.expires_at,
        ).on_conflict_do_nothing(index_elements=["bot_id"])
        result = self.db.execute(stmt)
        self.db.flush()
        return lease if result.rowcount > 0 else None

    def save_lease(self, lease: WorkerLease) -> WorkerLease:
        row = self.db.execute(select(WorkerLeaseModel).where(WorkerLeaseModel.bot_id == lease.bot_id)).scalar_one()
        row.worker_id = lease.worker_id
        row.lease_token = lease.lease_token
        row.lease_json = lease.model_dump(mode="json")
        row.heartbeat_at = lease.heartbeat_at
        row.expires_at = lease.expires_at
        self.db.flush()
        return lease

    def delete_lease(self, bot_id: str) -> None:
        row = self.db.execute(select(WorkerLeaseModel).where(WorkerLeaseModel.bot_id == bot_id)).scalar_one_or_none()
        if row is not None:
            self.db.delete(row)
            self.db.flush()
