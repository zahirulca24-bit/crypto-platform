"""Typed runtime configuration and fail-closed startup validation."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger("crypto_platform.startup")

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@postgres:5432/crypto_platform"
DEFAULT_REDIS_URL = "redis://redis:6379/0"
DEFAULT_JWT_SECRET = "dev_secret_key_change_in_production_987654321"


class RuntimeMode(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    DEMO = "demo"
    PRODUCTION = "production"


class TradingMode(str, Enum):
    DISABLED = "disabled"
    DEMO = "demo"
    LIVE = "live"


class StartupConfigurationError(RuntimeError):
    def __init__(self, reasons: list["ValidationReason"]):
        self.reasons = reasons
        super().__init__("Unsafe application configuration: " + "; ".join(r.message for r in reasons))


class ValidationReason(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    message: str


@dataclass(frozen=True)
class StartupValidationEvent:
    event: str
    runtime_mode: str
    trading_mode: str
    outcome: str
    reason_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "event": self.event,
            "runtime_mode": self.runtime_mode,
            "trading_mode": self.trading_mode,
            "outcome": self.outcome,
            "reason_codes": list(self.reason_codes),
        }


class AppSettings(BaseModel):
    """Application settings. Secret fields are never serialized by system endpoints."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_mode: RuntimeMode = RuntimeMode.DEVELOPMENT
    trading_mode: TradingMode = TradingMode.DISABLED
    debug: bool = False
    reload: bool = False
    development_features: bool = False
    sql_echo: bool = False

    database_url: str = DEFAULT_DATABASE_URL
    redis_url: str = DEFAULT_REDIS_URL
    jwt_secret_key: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    cors_allow_origins: tuple[str, ...] = ("http://localhost:3000", "http://localhost:3001")

    allow_live_trading: bool = False
    live_exchange_id: str = ""
    exchange_timeout_ms: int = Field(default=10_000, ge=1_000, le=30_000)
    exchange_max_safe_retries: int = Field(default=2, ge=0, le=5)
    exchange_retry_delay_seconds: float = Field(default=0.25, ge=0.0, le=5.0)

    safety_connectivity_failure_threshold: int = Field(default=3, ge=1, le=100)
    safety_order_error_threshold: int = Field(default=5, ge=1, le=100)
    safety_reconciliation_failure_threshold: int = Field(default=3, ge=1, le=100)
    safety_market_data_max_age_seconds: float = Field(default=30.0, gt=0.0, le=3600.0)
    safety_max_clock_drift_seconds: float = Field(default=5.0, gt=0.0, le=300.0)
    worker_lease_ttl_seconds: int = Field(default=30, ge=5, le=300)
    alert_min_interval_seconds: int = Field(default=300, ge=1, le=86400)
    credential_encryption_key: str = ""
    max_request_body_bytes: int = Field(default=1_048_576, ge=16_384, le=10_485_760)
    public_registration_enabled: bool = False
    public_env_violations: tuple[str, ...] = ()
    plaintext_exchange_env_violations: tuple[str, ...] = ()

    @field_validator("database_url", "redis_url", "jwt_secret_key", "jwt_algorithm")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            return ""
        return value.strip()

    @staticmethod
    def _bool(env: Mapping[str, str], name: str, default: bool = False) -> bool:
        raw = env.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AppSettings":
        source = os.environ if env is None else env
        origins = tuple(x.strip() for x in source.get("CORS_ALLOW_ORIGINS", "http://localhost:3000,http://localhost:3001").split(",") if x.strip())
        runtime_raw = source.get("RUNTIME_MODE", source.get("ENVIRONMENT", RuntimeMode.DEVELOPMENT.value)).strip().lower()
        public_env_violations = tuple(sorted(name for name in source if name.startswith("NEXT_PUBLIC_") and any(part in name.upper() for part in ("SECRET", "PASSWORD", "TOKEN", "API_KEY", "DATABASE", "REDIS", "JWT"))))
        plaintext_exchange_env_violations = tuple(
            sorted(
                name
                for name in tuple(
                    f"{mode}_{field}"
                    for mode in ("LIVE", "DEMO")
                    for field in ("API_KEY", "API_SECRET", "API_PASSWORD")
                )
                if str(source.get(name, "")).strip()
            )
        )
        return cls(
            runtime_mode=runtime_raw,
            trading_mode=source.get("TRADING_MODE", TradingMode.DISABLED.value).strip().lower(),
            debug=cls._bool(source, "DEBUG") or cls._bool(source, "APP_DEBUG"),
            reload=cls._bool(source, "RELOAD"),
            development_features=cls._bool(source, "DEVELOPMENT_FEATURES") or cls._bool(source, "DEV_MODE"),
            sql_echo=cls._bool(source, "SQL_ECHO"),
            database_url=source.get("DATABASE_URL") or f"postgresql://{source.get('POSTGRES_USER', 'postgres')}:{source.get('POSTGRES_PASSWORD', 'postgres')}@{source.get('POSTGRES_HOST', 'postgres')}:{source.get('POSTGRES_PORT', '5432')}/{source.get('POSTGRES_DB', 'crypto_platform')}",
            redis_url=source.get("REDIS_URL") or f"redis://{source.get('REDIS_HOST', 'redis')}:{source.get('REDIS_PORT', '6379')}/0",
            jwt_secret_key=source.get("JWT_SECRET_KEY", DEFAULT_JWT_SECRET),
            jwt_algorithm=source.get("JWT_ALGORITHM", "HS256"),
            jwt_access_token_expire_minutes=int(source.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")),
            cors_allow_origins=origins,
            allow_live_trading=cls._bool(source, "ALLOW_LIVE_TRADING"),
            live_exchange_id=source.get("LIVE_EXCHANGE_ID", "").strip().lower(),
            exchange_timeout_ms=int(source.get("EXCHANGE_TIMEOUT_MS", "10000")),
            exchange_max_safe_retries=int(source.get("EXCHANGE_MAX_SAFE_RETRIES", "2")),
            exchange_retry_delay_seconds=float(source.get("EXCHANGE_RETRY_DELAY_SECONDS", "0.25")),
            safety_connectivity_failure_threshold=int(source.get("SAFETY_CONNECTIVITY_FAILURE_THRESHOLD", "3")),
            safety_order_error_threshold=int(source.get("SAFETY_ORDER_ERROR_THRESHOLD", "5")),
            safety_reconciliation_failure_threshold=int(source.get("SAFETY_RECONCILIATION_FAILURE_THRESHOLD", "3")),
            safety_market_data_max_age_seconds=float(source.get("SAFETY_MARKET_DATA_MAX_AGE_SECONDS", "30")),
            safety_max_clock_drift_seconds=float(source.get("SAFETY_MAX_CLOCK_DRIFT_SECONDS", "5")),
            worker_lease_ttl_seconds=int(source.get("WORKER_LEASE_TTL_SECONDS", "30")),
            alert_min_interval_seconds=int(source.get("ALERT_MIN_INTERVAL_SECONDS", "300")),
            credential_encryption_key=source.get("CREDENTIAL_ENCRYPTION_KEY", "").strip(),
            max_request_body_bytes=int(source.get("MAX_REQUEST_BODY_BYTES", "1048576")),
            public_registration_enabled=cls._bool(source, "PUBLIC_REGISTRATION_ENABLED", default=runtime_raw in {"development","test"}),
            public_env_violations=public_env_violations,
            plaintext_exchange_env_violations=plaintext_exchange_env_violations,
        )

    def validation_reasons(self) -> list[ValidationReason]:
        reasons: list[ValidationReason] = []

        if self.trading_mode is TradingMode.LIVE:
            if self.runtime_mode is not RuntimeMode.PRODUCTION:
                reasons.append(ValidationReason(code="live_trading_requires_production", message="Live trading is permitted only in production runtime mode."))
            if not self.allow_live_trading:
                reasons.append(ValidationReason(code="live_trading_not_explicitly_enabled", message="Live trading requires an explicit live-trading enable flag."))
            if not self.live_exchange_id:
                reasons.append(ValidationReason(code="live_exchange_required", message="Live trading requires an explicit exchange identifier."))

        if self.runtime_mode is RuntimeMode.PRODUCTION:
            if self.debug or self.reload or self.development_features or self.sql_echo:
                reasons.append(ValidationReason(code="production_debug_flags_enabled", message="Debug, reload, development-only, and SQL echo flags must be disabled in production."))
            if not self.database_url or not self.database_url.lower().startswith(("postgresql://", "postgresql+psycopg2://")):
                reasons.append(ValidationReason(code="production_postgresql_required", message="Production requires an explicit PostgreSQL DATABASE_URL."))
            if self.database_url == DEFAULT_DATABASE_URL:
                reasons.append(ValidationReason(code="production_default_database_credentials", message="Production may not use the development default database URL."))
            if not self.redis_url or not self.redis_url.lower().startswith(("redis://", "rediss://")):
                reasons.append(ValidationReason(code="production_redis_required", message="Production requires an explicit Redis/Valkey URL."))
            elif self.redis_url == DEFAULT_REDIS_URL:
                reasons.append(ValidationReason(code="production_default_redis_configuration", message="Production may not use the development default Redis/Valkey URL."))
            if not self.jwt_secret_key or self.jwt_secret_key == DEFAULT_JWT_SECRET or len(self.jwt_secret_key) < 32:
                reasons.append(ValidationReason(code="production_jwt_secret_required", message="Production requires a non-default JWT secret of at least 32 characters."))
            if self.jwt_algorithm not in {"HS256", "HS384", "HS512"}:
                reasons.append(ValidationReason(code="production_jwt_algorithm_unsafe", message="Production JWT algorithm must be an explicitly supported HMAC algorithm."))
            if any(origin == "*" for origin in self.cors_allow_origins):
                reasons.append(ValidationReason(code="production_wildcard_cors_forbidden", message="Wildcard CORS is forbidden in production."))
            if any(not origin.lower().startswith("https://") for origin in self.cors_allow_origins):
                reasons.append(ValidationReason(code="production_https_cors_required", message="Production CORS origins must use HTTPS."))
            if not self.cors_allow_origins:
                reasons.append(ValidationReason(code="production_cors_origins_required", message="Production requires an explicit CORS allowlist."))
            if self.credential_encryption_key and len(self.credential_encryption_key) != 44:
                reasons.append(ValidationReason(code="production_credential_encryption_key_invalid", message="Configured production credential encryption key must be Fernet-compatible."))
            if self.public_env_violations:
                reasons.append(ValidationReason(code="public_environment_secret_name_forbidden", message="NEXT_PUBLIC_* environment variables must not be used for backend credentials or secrets."))
            if self.plaintext_exchange_env_violations:
                reasons.append(ValidationReason(code="production_plaintext_exchange_env_forbidden", message="Production exchange credentials must use the encrypted credential store, not plaintext environment variables."))
            if any("localhost" in origin.lower() or "127.0.0.1" in origin for origin in self.cors_allow_origins):
                reasons.append(ValidationReason(code="production_local_cors_forbidden", message="Production CORS origins must not use local development origins."))
            if self.trading_mode is TradingMode.DEMO:
                reasons.append(ValidationReason(code="production_demo_trading_forbidden", message="Production runtime mode cannot use demo trading mode."))

        return reasons

    def validate_startup(self) -> StartupValidationEvent:
        reasons = self.validation_reasons()
        event = StartupValidationEvent(
            event="startup.configuration_validation",
            runtime_mode=self.runtime_mode.value,
            trading_mode=self.trading_mode.value,
            outcome="rejected" if reasons else "accepted",
            reason_codes=tuple(reason.code for reason in reasons),
        )
        # Deliberately only mode/outcome/reason codes: no URLs, keys, credentials, or raw env values.
        logger.log(logging.ERROR if reasons else logging.INFO, json.dumps(event.as_dict(), sort_keys=True))
        if reasons:
            raise StartupConfigurationError(reasons)
        return event
