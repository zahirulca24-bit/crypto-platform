"""Observability domain exports without initializing database drivers at import time."""
from .logging import JsonFormatter, correlation_id, configure_structured_logging, redact
from .models import AlertDispatchResult, AlertSeverity, OperationalAlert, OperationalIncident
from .service import AlertService, ObservabilityService

__all__ = [
    'JsonFormatter','correlation_id','configure_structured_logging','redact',
    'AlertDispatchResult','AlertSeverity','OperationalAlert','OperationalIncident',
    'AlertService','ObservabilityService','ObservabilityStore',
]


def __getattr__(name):
    if name == 'ObservabilityStore':
        from .storage import ObservabilityStore
        return ObservabilityStore
    raise AttributeError(name)
