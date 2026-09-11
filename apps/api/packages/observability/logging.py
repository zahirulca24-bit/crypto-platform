from __future__ import annotations

import contextvars
import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar('correlation_id', default=None)
bot_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar('bot_id', default=None)
runtime_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar('runtime_id', default=None)

_SENSITIVE_KEY_PARTS = ('secret','password','passwd','authorization','api_key','apikey','private_key','credential','cookie','jwt','access_token','refresh_token')
_BEARER = re.compile(r'(?i)\b(Bearer)\s+[A-Za-z0-9._~+\-/]+=*')
_URL_CREDS = re.compile(r'(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<user>[^/@:\s]+):(?P<password>[^/@\s]+)@')
_KEY_VALUE = re.compile(r'(?i)\b(api[_-]?key|secret|password|token)\s*[=:]\s*([^\s,;]+)')


def _sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def redact(value: Any, *, key: str | None = None) -> Any:
    """Recursively remove credentials while retaining diagnostic-safe IDs/context."""
    if key is not None and _sensitive_key(key):
        return '[REDACTED]'
    if isinstance(value, dict):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        result = _BEARER.sub(r'\1 [REDACTED]', value)
        result = _URL_CREDS.sub(r'\g<scheme>[REDACTED]:[REDACTED]@', result)
        result = _KEY_VALUE.sub(lambda m: f'{m.group(1)}=[REDACTED]', result)
        return result
    if isinstance(value, (datetime, date, UUID, Decimal)):
        return str(value)
    return value


class JsonFormatter(logging.Formatter):
    RESERVED = set(logging.LogRecord('',0,'',0,'',(),None).__dict__) | {'message','asctime'}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            'timestamp': datetime.now(__import__('datetime').timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),
            'level': record.levelname.lower(),
            'logger': record.name,
            'message': redact(record.getMessage()),
        }
        cid = getattr(record, 'correlation_id', None) or correlation_id.get()
        bid = getattr(record, 'bot_id', None) or bot_id_context.get()
        rid = getattr(record, 'runtime_id', None) or runtime_id_context.get()
        if cid: payload['correlation_id'] = cid
        if bid: payload['bot_id'] = bid
        if rid: payload['runtime_id'] = rid
        for k, v in record.__dict__.items():
            if k not in self.RESERVED and not k.startswith('_') and k not in {'correlation_id','bot_id','runtime_id'}:
                payload[k] = redact(v, key=k)
        if record.exc_info:
            payload['exception_type'] = record.exc_info[0].__name__ if record.exc_info[0] else 'Exception'
            # Deliberately do not serialize exception messages/traceback: exchange libraries
            # sometimes include request headers or credentials in them.
        return json.dumps(redact(payload), sort_keys=True, separators=(',', ':'), default=str)


def configure_structured_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(getattr(h, '_crypto_json_handler', False) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler._crypto_json_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
