"""Supervised trading-runtime worker entrypoint.

This process owns the durable bot lease, performs startup reconciliation, and
maintains runtime heartbeats.  Strategy/risk/order execution remains inside the
existing governed services; this entrypoint does not bypass them.
"""
from __future__ import annotations

import logging
import os
import time

from database import SessionLocal
from settings import AppSettings
from packages.exchange.factory import build_execution_gateway
from packages.exchange.storage import DemoOrderStore
from packages.positions.engine import PositionEngine
from packages.positions.storage import PositionStore
from packages.protection.service import ProtectionService
from packages.protection.storage import ProtectionStore
from packages.reconciliation import ReconciliationService, ReconciliationStore, GatewayRecoveryReader, WorkerLeaseService
from packages.runtime.service import BotRuntime
from packages.runtime.storage import RuntimeStore
from packages.safety.models import CircuitBreakerType
from packages.safety.service import SafetyControlService
from packages.safety.storage import SafetyStore
from packages.observability import AlertService, ObservabilityService, ObservabilityStore
from exchange.credential_security import ExchangeCredentialService

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("crypto_platform.trading_worker")


class DisabledRecoveryReader:
    def lookup_order(self, order):
        return None

    def open_positions(self):
        return None


def _gateway(settings: AppSettings, db):
    if settings.trading_mode.value != "live":
        return build_execution_gateway(settings)
    credentials = ExchangeCredentialService(
        db,
        encryption_key=settings.credential_encryption_key,
        timeout_ms=settings.exchange_timeout_ms,
    )
    return build_execution_gateway(settings, credential_resolver=credentials.resolve_for_execution)


def build_runtime(db, settings: AppSettings) -> BotRuntime:
    obs_store = ObservabilityStore(db)
    observability = ObservabilityService(
        obs_store,
        AlertService(obs_store, min_interval_seconds=settings.alert_min_interval_seconds),
    )
    safety = SafetyControlService(
        SafetyStore(db),
        thresholds={
            CircuitBreakerType.EXCHANGE_CONNECTIVITY: settings.safety_connectivity_failure_threshold,
            CircuitBreakerType.EXCESSIVE_ORDER_ERRORS: settings.safety_order_error_threshold,
            CircuitBreakerType.RECONCILIATION_FAILURE: settings.safety_reconciliation_failure_threshold,
        },
        incident_reporter=observability,
    )
    positions = PositionEngine(PositionStore(db))
    protection = ProtectionService(positions.store, ProtectionStore(db))
    gateway = _gateway(settings, db)
    reader = GatewayRecoveryReader(gateway) if gateway is not None else DisabledRecoveryReader()
    reconciliation_store = ReconciliationStore(db)
    reconciliation = ReconciliationService(
        reconciliation_store,
        DemoOrderStore(db),
        positions,
        protection,
        reader,
        safety,
        incident_reporter=observability,
    )
    leases = WorkerLeaseService(reconciliation_store, ttl_seconds=settings.worker_lease_ttl_seconds)
    return BotRuntime(
        RuntimeStore(db),
        safety_service=safety,
        reconciliation_service=reconciliation,
        lease_service=leases,
        bot_id=os.getenv("BOT_ID", "demo-bot"),
    )


def main() -> None:
    settings = AppSettings.from_env()
    settings.validate_startup()
    worker_id = os.getenv("WORKER_ID", "trading-worker")
    supervisor_id = os.getenv("SUPERVISOR_ID", "compose")
    interval = max(1.0, float(os.getenv("WORKER_HEARTBEAT_SECONDS", "5")))
    db = SessionLocal()
    runtime = build_runtime(db, settings)
    try:
        runtime.recover(supervisor_id=supervisor_id, worker_id=worker_id)
        logger.info("trading_worker.started", extra={"bot_id": runtime.bot_id, "runtime_id": worker_id})
        while True:
            runtime.tick(supervisor_id=supervisor_id, worker_id=worker_id)
            time.sleep(interval)
    finally:
        try:
            if runtime._lease is not None and runtime.lease_service is not None:
                runtime.lease_service.release(runtime.bot_id, worker_id, runtime._lease.lease_token)
        finally:
            db.close()


if __name__ == "__main__":
    main()
