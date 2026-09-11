"""Encrypted exchange credential lifecycle inside the approved exchange boundary.

Plaintext credentials enter only as short-lived method arguments, are never returned,
and are encrypted before persistence. This module exposes no withdrawal operation.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from packages.exchange.execution import ExecutionMode
from packages.observability.logging import redact


class CredentialEncryptionUnavailable(RuntimeError): pass
class CredentialValidationFailed(RuntimeError): pass


@dataclass(frozen=True)
class CredentialMetadata:
    id: UUID
    exchange_id: str
    environment: str
    api_key_fingerprint: str
    validation_status: str
    validated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CredentialCipher:
    def __init__(self, key: str):
        if not key:
            raise CredentialEncryptionUnavailable("Credential encryption key is not configured")
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except Exception as exc:
            raise CredentialEncryptionUnavailable("Credential encryption key is invalid") from exc

    def encrypt(self, value: str) -> bytes:
        return self._fernet.encrypt(value.encode("utf-8"))

    def decrypt(self, value: bytes) -> str:
        try:
            return self._fernet.decrypt(value).decode("utf-8")
        except InvalidToken as exc:
            raise CredentialEncryptionUnavailable("Stored credential cannot be decrypted") from exc


def api_key_fingerprint(api_key: str) -> str:
    return "sha256:" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


class SecurityAuditStore:
    def __init__(self, db): self.db = db

    def record(self, *, actor_user_id, action: str, outcome: str, target_type: str, target_id: str | None, request_id: str | None, context: dict | None = None):
        from models import SecurityAuditEventModel
        row = SecurityAuditEventModel(
            actor_user_id=actor_user_id, action=action, outcome=outcome,
            target_type=target_type, target_id=target_id, request_id=request_id,
            context_json=redact(context or {}),
        )
        self.db.add(row); self.db.commit(); self.db.refresh(row)
        return row

    def list(self, limit: int = 100, offset: int = 0):
        from models import SecurityAuditEventModel
        return self.db.execute(select(SecurityAuditEventModel).order_by(SecurityAuditEventModel.created_at.desc()).offset(offset).limit(limit)).scalars().all()


class ExchangeCredentialService:
    def __init__(self, db, *, encryption_key: str, timeout_ms: int = 10_000):
        self.db = db; self.cipher = CredentialCipher(encryption_key); self.timeout_ms = timeout_ms

    @staticmethod
    def _metadata(row) -> CredentialMetadata:
        return CredentialMetadata(
            id=row.id, exchange_id=row.exchange_id, environment=row.environment,
            api_key_fingerprint=row.api_key_fingerprint,
            validation_status=row.validation_status, validated_at=row.validated_at,
            created_at=row.created_at, updated_at=row.updated_at,
        )

    def list_metadata(self) -> list[CredentialMetadata]:
        from models import ExchangeCredentialModel
        rows = self.db.execute(select(ExchangeCredentialModel).order_by(ExchangeCredentialModel.exchange_id, ExchangeCredentialModel.environment)).scalars().all()
        return [self._metadata(r) for r in rows]

    def resolve_for_execution(self, *, exchange_id: str, environment: str) -> dict[str, str]:
        """Resolve a validated credential for the approved execution boundary.

        Plaintext exists only for the lifetime of this return value and is never
        serialized, logged, or exposed by an API response.  Callers outside the
        exchange/execution boundary must use metadata APIs instead.
        """
        from models import ExchangeCredentialModel

        row = self.db.execute(
            select(ExchangeCredentialModel).where(
                ExchangeCredentialModel.exchange_id == exchange_id.lower().strip(),
                ExchangeCredentialModel.environment == environment,
            )
        ).scalar_one_or_none()
        if row is None or row.validation_status != "validated":
            raise CredentialValidationFailed("Validated exchange credential is unavailable")
        return {
            "api_key": self.cipher.decrypt(row.api_key_ciphertext),
            "api_secret": self.cipher.decrypt(row.api_secret_ciphertext),
            "password": self.cipher.decrypt(row.password_ciphertext) if row.password_ciphertext else "",
        }

    def validate_transient(self, *, exchange_id: str, environment: str, api_key: str, api_secret: str, password: str | None = None) -> dict:
        """Read-only validation; plaintext is neither logged nor persisted."""
        if environment not in {"demo", "live"}: raise ValueError("Unsupported credential environment")
        # CCXT construction remains inside the approved exchange boundary.
        from exchange.execution_adapter import CCXTExecutionAdapter
        prefix = "DEMO" if environment == "demo" else "LIVE"
        adapter = CCXTExecutionAdapter(
            exchange_id=exchange_id,
            mode=ExecutionMode(environment),
            credentials={"api_key": api_key, "api_secret": api_secret, "password": password or ""},
            timeout_ms=self.timeout_ms,
        )
        caps = adapter.validate_account_capabilities()
        if not caps.authenticated:
            raise CredentialValidationFailed("Credential validation failed")
        return {
            "exchange_id": exchange_id,
            "environment": environment,
            "api_key_fingerprint": api_key_fingerprint(api_key),
            "authenticated": caps.authenticated,
            "can_trade": caps.can_trade,
            "supports_client_order_id": caps.supports_client_order_id,
            "withdrawal_supported_by_application": False,
            "reason_codes": list(caps.reason_codes),
        }

    def store_validated(self, *, actor_user_id: UUID, exchange_id: str, environment: str, api_key: str, api_secret: str, password: str | None = None) -> CredentialMetadata:
        validation = self.validate_transient(exchange_id=exchange_id, environment=environment, api_key=api_key, api_secret=api_secret, password=password)
        from models import ExchangeCredentialModel
        row = self.db.execute(select(ExchangeCredentialModel).where(
            ExchangeCredentialModel.exchange_id == exchange_id,
            ExchangeCredentialModel.environment == environment,
        ).with_for_update()).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        values = dict(
            api_key_ciphertext=self.cipher.encrypt(api_key),
            api_secret_ciphertext=self.cipher.encrypt(api_secret),
            password_ciphertext=self.cipher.encrypt(password) if password else None,
            api_key_fingerprint=validation["api_key_fingerprint"],
            validation_status="validated", validated_at=now, updated_by=actor_user_id,
        )
        if row is None:
            row = ExchangeCredentialModel(exchange_id=exchange_id, environment=environment, created_by=actor_user_id, **values)
            self.db.add(row)
        else:
            for k, v in values.items(): setattr(row, k, v)
        self.db.commit(); self.db.refresh(row)
        return self._metadata(row)

    def delete(self, credential_id: UUID) -> bool:
        from models import ExchangeCredentialModel
        row = self.db.get(ExchangeCredentialModel, credential_id)
        if row is None: return False
        self.db.delete(row); self.db.commit(); return True
