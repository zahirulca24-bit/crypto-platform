from __future__ import annotations
from typing import Any
import re

SENSITIVE_MARKERS = (
    "api_key", "apikey", "api_secret", "secret", "password", "passwd", "jwt",
    "private_key", "credential", "encrypted_credential", "withdrawal", "database_url",
    "postgres_password", "access_token", "refresh_token",
)
DANGEROUS_VALUE_KEYS = {"code", "python", "script", "shell", "command", "executable"}

def _sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_MARKERS)

def sanitize_context(value: Any, *, depth: int = 0, max_depth: int = 8) -> Any:
    if depth > max_depth:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            key_s = str(key)
            if _sensitive_key(key_s):
                continue
            clean[key_s] = sanitize_context(item, depth=depth + 1, max_depth=max_depth)
        return clean
    if isinstance(value, list):
        return [sanitize_context(item, depth=depth + 1, max_depth=max_depth) for item in value[:200]]
    if isinstance(value, tuple):
        return [sanitize_context(item, depth=depth + 1, max_depth=max_depth) for item in value[:200]]
    if isinstance(value, str):
        if "-----BEGIN " in value and "PRIVATE KEY-----" in value:
            return "[REDACTED]"
        if re.search(r"(?i)(api[_-]?key|api[_-]?secret|password|passwd|access[_-]?token|jwt[_-]?secret)\s*[:=]\s*\S+", value):
            return "[REDACTED]"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)

def validate_condition_safety(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in DANGEROUS_VALUE_KEYS:
                raise ValueError("executable/code fields are not allowed in AI proposal conditions")
            validate_condition_safety(value)
    elif isinstance(payload, list):
        for value in payload:
            validate_condition_safety(value)
