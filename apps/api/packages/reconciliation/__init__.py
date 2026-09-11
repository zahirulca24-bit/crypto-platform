"""Durable reconciliation and worker ownership domain."""
from .models import *


def __getattr__(name):
    if name in {"ReconciliationService", "GatewayRecoveryReader", "WorkerLeaseService"}:
        from .service import ReconciliationService, GatewayRecoveryReader, WorkerLeaseService
        return {"ReconciliationService": ReconciliationService, "GatewayRecoveryReader": GatewayRecoveryReader, "WorkerLeaseService": WorkerLeaseService}[name]
    if name == "ReconciliationStore":
        from .storage import ReconciliationStore
        return ReconciliationStore
    raise AttributeError(name)
