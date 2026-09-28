from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from packages.exchange.models import DemoOrder, OrderStatus
from packages.positions.models import PositionStatus
from packages.protection.models import ProtectionStatus
from packages.safety.models import CircuitBreakerType, SafetyHaltRequest, SafetyScope

from .models import (
    DiscrepancySeverity, ExchangePositionSnapshot, LeaseAcquireResult,
    ReconciliationDiscrepancy, ReconciliationRun, ReconciliationRunStatus,
    ReconciliationStatus, WorkerLease,
)


class RecoveryStateReader(Protocol):
    def lookup_order(self, order: DemoOrder): ...
    def open_positions(self) -> list[ExchangePositionSnapshot] | None: ...


class GatewayRecoveryReader:
    """Read-only exchange recovery view. It never exposes an order submission method."""
    def __init__(self, gateway):
        self.gateway = gateway

    def lookup_order(self, order: DemoOrder):
        return self.gateway.reconcile(order)

    def open_positions(self) -> list[ExchangePositionSnapshot] | None:
        fn = getattr(self.gateway.adapter, "fetch_open_positions", None)
        if fn is None:
            return None
        snapshot = fn()
        return None if snapshot is None else list(snapshot)


class WorkerLeaseService:
    def __init__(self, store, *, ttl_seconds: int = 30, now_fn=None):
        self.store = store
        self.ttl_seconds = max(5, int(ttl_seconds))
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def acquire(self, bot_id: str, worker_id: str) -> LeaseAcquireResult:
        now = self.now_fn()
        with self.store.locked_lease(bot_id):
            existing = self.store.load_lease(bot_id)
            if existing and existing.expires_at > now and existing.worker_id != worker_id:
                return LeaseAcquireResult(acquired=False, lease=existing, reason_code="lease_owned_by_active_worker")
            if existing and existing.worker_id == worker_id:
                existing.heartbeat_at = now
                existing.expires_at = now + timedelta(seconds=self.ttl_seconds)
                return LeaseAcquireResult(acquired=True, lease=self.store.save_lease(existing))
            lease = WorkerLease(bot_id=bot_id, worker_id=worker_id, acquired_at=now, heartbeat_at=now, expires_at=now + timedelta(seconds=self.ttl_seconds))
            if existing:
                self.store.delete_lease(bot_id)
            created = self.store.create_lease(lease)
            if created is None:
                current = self.store.load_lease(bot_id)
                return LeaseAcquireResult(acquired=False, lease=current, reason_code="lease_acquire_race_lost")
            return LeaseAcquireResult(acquired=True, lease=created)

    def heartbeat(self, bot_id: str, worker_id: str, lease_token: UUID) -> WorkerLease:
        now = self.now_fn()
        with self.store.locked_lease(bot_id):
            lease = self.store.load_lease(bot_id)
            if lease is None or lease.worker_id != worker_id or lease.lease_token != lease_token:
                raise RuntimeError("worker_lease_not_owned")
            if lease.expires_at <= now:
                raise RuntimeError("worker_lease_expired")
            lease.heartbeat_at = now
            lease.expires_at = now + timedelta(seconds=self.ttl_seconds)
            return self.store.save_lease(lease)

    def release(self, bot_id: str, worker_id: str, lease_token: UUID) -> bool:
        with self.store.locked_lease(bot_id):
            lease = self.store.load_lease(bot_id)
            if lease is None:
                return True
            if lease.worker_id != worker_id or lease.lease_token != lease_token:
                return False
            self.store.delete_lease(bot_id)
            return True


class ReconciliationService:
    def __init__(self, store, order_store, position_engine, protection_service, recovery_reader: RecoveryStateReader, safety_service=None, incident_reporter=None):
        self.store = store
        self.order_store = order_store
        self.position_engine = position_engine
        self.protection_service = protection_service
        self.recovery_reader = recovery_reader
        self.safety_service = safety_service
        self.incident_reporter = incident_reporter

    def _issue(self, run, *, kind, severity, entity_type, entity_id, reason_code, symbol=None, local=None, remote=None):
        d = ReconciliationDiscrepancy(
            run_id=run.id, kind=kind, severity=severity, entity_type=entity_type,
            entity_id=str(entity_id), symbol=symbol, reason_code=reason_code,
            local_state=local or {}, exchange_state=remote or {},
        )
        self.store.add_discrepancy(d)
        return d

    @staticmethod
    def _order_state(order: DemoOrder) -> dict:
        return {"status": order.status.value, "filled_quantity": str(order.filled_quantity), "exchange_order_id": order.exchange_order_id, "reconciliation_required": order.reconciliation_required}

    def run(self, *, bot_id: str = "demo-bot", worker_id: str | None = None, trigger: str = "startup") -> ReconciliationRun:
        run = self.store.create_run(ReconciliationRun(bot_id=bot_id, worker_id=worker_id, trigger=trigger))
        issues = []
        try:
            for order in self.order_store.list(limit=5000):
                try:
                    remote = self.recovery_reader.lookup_order(order)
                except Exception:
                    remote = None
                    issues.append(self._issue(run, kind="order_lookup_ambiguous", severity=DiscrepancySeverity.SEVERE, entity_type="order", entity_id=order.id, symbol=order.symbol, reason_code="exchange_order_lookup_failed", local=self._order_state(order)))
                    continue
                if remote is None:
                    severity = DiscrepancySeverity.SEVERE if order.status in {OrderStatus.PENDING, OrderStatus.SUBMITTING, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED, OrderStatus.UNKNOWN} else DiscrepancySeverity.WARNING
                    issues.append(self._issue(run, kind="order_missing_on_exchange", severity=severity, entity_type="order", entity_id=order.id, symbol=order.symbol, reason_code="exchange_order_not_found", local=self._order_state(order)))
                    if severity is DiscrepancySeverity.SEVERE:
                        order.reconciliation_required = True
                        self.order_store.update(order)
                    continue

                remote_state = {"status": remote.status.value, "filled_quantity": str(remote.filled_quantity), "exchange_order_id": remote.exchange_order_id}
                changed = order.status != remote.status or order.filled_quantity != remote.filled_quantity or order.exchange_order_id != remote.exchange_order_id
                if changed:
                    severity = DiscrepancySeverity.SEVERE if remote.status is OrderStatus.UNKNOWN else DiscrepancySeverity.WARNING
                    issues.append(self._issue(run, kind="order_state_mismatch", severity=severity, entity_type="order", entity_id=order.id, symbol=order.symbol, reason_code="order_state_differs", local=self._order_state(order), remote=remote_state))
                    if remote.status is not OrderStatus.UNKNOWN:
                        order.status = remote.status
                        order.filled_quantity = remote.filled_quantity
                        order.exchange_order_id = remote.exchange_order_id or order.exchange_order_id
                        order.fee = remote.fee
                        order.raw_exchange_response = remote.raw
                        order.reconciliation_required = False
                        self.order_store.update(order)
                if remote.status is OrderStatus.FILLED and remote.filled_quantity > 0:
                    self.position_engine.apply_filled_order(order)

            remote_positions = self.recovery_reader.open_positions()
            local_positions = self.position_engine.store.list(limit=5000)
            if remote_positions is None:
                if any(p.status is PositionStatus.OPEN for p in local_positions):
                    issues.append(self._issue(run, kind="position_state_ambiguous", severity=DiscrepancySeverity.SEVERE, entity_type="portfolio", entity_id=bot_id, reason_code="exchange_position_snapshot_unavailable"))
            else:
                remote_by_symbol = {p.symbol: p for p in remote_positions if p.quantity > 0}
                local_open_symbols = {p.symbol for p in local_positions if p.status is PositionStatus.OPEN}
                for pos in local_positions:
                    remote = remote_by_symbol.get(pos.symbol)
                    if pos.status is PositionStatus.OPEN:
                        if remote is None:
                            issues.append(self._issue(run, kind="open_position_missing_on_exchange", severity=DiscrepancySeverity.SEVERE, entity_type="position", entity_id=pos.id, symbol=pos.symbol, reason_code="position_missing_on_exchange", local={"status": pos.status.value, "side": pos.side.value, "quantity": str(pos.quantity)}))
                        elif remote.side.lower() != pos.side.value or remote.quantity != pos.quantity:
                            issues.append(self._issue(run, kind="position_state_mismatch", severity=DiscrepancySeverity.SEVERE, entity_type="position", entity_id=pos.id, symbol=pos.symbol, reason_code="position_state_differs", local={"status": pos.status.value, "side": pos.side.value, "quantity": str(pos.quantity)}, remote=remote.model_dump(mode="json")))
                    elif remote is not None and remote.quantity > 0 and pos.symbol not in local_open_symbols:
                        issues.append(self._issue(run, kind="closed_position_still_open", severity=DiscrepancySeverity.SEVERE, entity_type="position", entity_id=pos.id, symbol=pos.symbol, reason_code="closed_position_present_on_exchange", local={"status": pos.status.value}, remote=remote.model_dump(mode="json")))

            # Existing protection reconciliation is intentionally retained. It is idempotent via persisted protection IDs/client IDs.
            for protection in self.protection_service.reconcile():
                if protection.protection_status in {ProtectionStatus.MISSING, ProtectionStatus.PARTIAL, ProtectionStatus.ERROR}:
                    issues.append(self._issue(run, kind="protection_not_fully_recovered", severity=DiscrepancySeverity.SEVERE, entity_type="protection", entity_id=protection.position_id, reason_code=f"protection_{protection.protection_status.value}", local=protection.model_dump(mode="json")))

            severe = sum(i.severity is DiscrepancySeverity.SEVERE and i.status.value == "open" for i in issues)
            run.discrepancy_count = len(issues)
            run.severe_unresolved_count = severe
            run.status = ReconciliationRunStatus.BLOCKED if severe else ReconciliationRunStatus.COMPLETED
            run.completed_at = datetime.now(timezone.utc)
            run.summary = {"orders_checked": len(self.order_store.list(limit=5000)), "positions_checked": len(local_positions), "severe_unresolved": severe}
            self.store.save_run(run)
            if severe and self.incident_reporter is not None:
                self.incident_reporter.report_incident(incident_key=f"reconciliation:{bot_id}:severe",category="reconciliation",severity="critical",title="Severe reconciliation discrepancies block new execution",context={"bot_id":bot_id,"worker_id":worker_id,"run_id":str(run.id),"severe_unresolved_count":severe,"trigger":trigger})
            if self.safety_service is not None:
                if severe:
                    # Severe reconciliation discrepancies block immediately, regardless of the
                    # rolling failure threshold used for transient reconciliation errors.
                    self.safety_service.halt(SafetyHaltRequest(
                        idempotency_key=f"recon-{run.id}", scope=SafetyScope.CIRCUIT,
                        scope_key=CircuitBreakerType.RECONCILIATION_FAILURE.value,
                        reason_code="severe_reconciliation_discrepancy", operator_id="reconciliation-worker",
                    ))
                else:
                    self.store.resolve_open_severe()
                    # Healthy recovery is observed but the severe circuit is deliberately not
                    # auto-resumed; an operator must still explicitly acknowledge/resume it.
                    self.safety_service.record_success(CircuitBreakerType.RECONCILIATION_FAILURE)
            elif not severe:
                self.store.resolve_open_severe()
            return run
        except Exception:
            run.status = ReconciliationRunStatus.FAILED
            run.completed_at = datetime.now(timezone.utc)
            run.severe_unresolved_count = max(run.severe_unresolved_count, 1)
            self.store.save_run(run)
            if self.safety_service is not None:
                self.safety_service.record_failure(CircuitBreakerType.RECONCILIATION_FAILURE, reason_code="reconciliation_run_failed")
            raise

    def status(self, *, bot_id: str = "demo-bot", active_lease=None) -> ReconciliationStatus:
        severe = self.store.severe_unresolved_count()
        return ReconciliationStatus(latest_run=self.store.latest_run(bot_id), severe_unresolved_count=severe, execution_blocked=severe > 0, active_lease=active_lease)
