"""Production-grade exchange execution boundary.

Only the Order Engine may submit orders through :class:`ExecutionGateway`.
Adapters are responsible for venue-specific behavior and credential access.  The
boundary deliberately exposes no withdrawal operation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from time import sleep as default_sleep
from typing import Any, Callable, Protocol

from .models import DemoOrder, OrderStatus

logger = logging.getLogger("crypto_platform.execution")


class ExecutionMode(str, Enum):
    DEMO = "demo"
    LIVE = "live"


@dataclass(frozen=True)
class AccountCapabilities:
    authenticated: bool
    can_trade: bool
    supports_client_order_id: bool
    spot_enabled: bool = True
    reason_codes: tuple[str, ...] = ()

    @property
    def live_ready(self) -> bool:
        return self.authenticated and self.can_trade and self.supports_client_order_id and self.spot_enabled


@dataclass(frozen=True)
class ExecutionResult:
    exchange_order_id: str | None
    status: OrderStatus
    filled_quantity: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")
    raw: dict[str, Any] = field(default_factory=dict)


class ExecutionAdapter(Protocol):
    """Venue adapter contract. Credentials, when needed, stay behind this interface."""

    mode: ExecutionMode

    def validate_account_capabilities(self) -> AccountCapabilities: ...
    def submit_order(self, order: DemoOrder) -> ExecutionResult: ...
    def find_order_by_client_id(self, client_order_id: str, symbol: str) -> ExecutionResult | None: ...


class ExecutionError(RuntimeError):
    code = "execution_error"
    retryable = False
    state_unknown = False

    def __init__(self, message: str = "Exchange execution failed") -> None:
        # Messages must be sanitized by adapters; the gateway never logs raw credentials/config.
        super().__init__(message)


class ExecutionDisabledError(ExecutionError):
    code = "execution_disabled"


class LiveExecutionNotAllowedError(ExecutionError):
    code = "live_execution_not_allowed"


class AccountCapabilityError(ExecutionError):
    code = "account_capability_invalid"


class ExchangeAuthenticationError(ExecutionError):
    code = "exchange_authentication_failed"


class ExchangePermissionError(ExecutionError):
    code = "exchange_permission_denied"


class ExchangeOrderRejectedError(ExecutionError):
    code = "exchange_order_rejected"


class ExchangeRateLimitError(ExecutionError):
    code = "exchange_rate_limited"
    retryable = True


class ExchangePreflightTimeoutError(ExecutionError):
    code = "exchange_preflight_timeout"
    retryable = True


class SafeToRetrySubmissionError(ExecutionError):
    """Adapter guarantees the request was not transmitted to the exchange."""

    code = "submission_not_sent_retryable"
    retryable = True


class UnknownOrderStateError(ExecutionError):
    """Submission may have reached the venue; reconciliation is mandatory."""

    code = "unknown_order_state"
    state_unknown = True


class ExecutionGateway:
    """The single order-submission gateway below the Order Engine.

    Live execution requires every explicit gate.  Submission retries are limited
    to errors that positively guarantee the order was never transmitted.  Any
    ambiguous timeout/network response becomes UNKNOWN and must be reconciled.
    """

    def __init__(
        self,
        adapter: ExecutionAdapter,
        *,
        mode: ExecutionMode | str,
        runtime_mode: str = "development",
        allow_live_trading: bool = False,
        max_safe_retries: int = 2,
        retry_delay_seconds: float = 0.0,
        sleep_fn: Callable[[float], None] = default_sleep,
    ) -> None:
        self.adapter = adapter
        self.mode = ExecutionMode(mode)
        self.runtime_mode = runtime_mode.lower()
        self.allow_live_trading = allow_live_trading
        self.max_safe_retries = max(0, max_safe_retries)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        self.sleep_fn = sleep_fn
        if adapter.mode is not self.mode:
            raise ValueError("Execution adapter mode does not match gateway mode")

    def _validate_live_gate(self) -> None:
        if self.mode is not ExecutionMode.LIVE:
            return
        if self.runtime_mode != "production" or not self.allow_live_trading:
            raise LiveExecutionNotAllowedError("Live execution safety gates are not enabled")

    def validate_account(self) -> AccountCapabilities:
        self._validate_live_gate()
        attempts = 0
        while True:
            try:
                caps = self.adapter.validate_account_capabilities()
                if self.mode is ExecutionMode.LIVE and not caps.live_ready:
                    raise AccountCapabilityError("Exchange account does not satisfy live execution capabilities")
                return caps
            except (ExchangeRateLimitError, ExchangePreflightTimeoutError):
                if attempts >= self.max_safe_retries:
                    raise
                attempts += 1
                if self.retry_delay_seconds:
                    self.sleep_fn(self.retry_delay_seconds)

    def submit(self, order: DemoOrder) -> ExecutionResult:
        self._validate_live_gate()
        # Account validation is read-only and safely retryable under the typed rules above.
        self.validate_account()

        attempts = 0
        while True:
            try:
                return self.adapter.submit_order(order)
            except SafeToRetrySubmissionError:
                if attempts >= self.max_safe_retries:
                    raise
                attempts += 1
                if self.retry_delay_seconds:
                    self.sleep_fn(self.retry_delay_seconds)
            except UnknownOrderStateError:
                # Never resubmit here. The deterministic client ID is used by reconciliation.
                raise
            except ExecutionError:
                raise
            except Exception as exc:
                # Unknown adapter exceptions after submission begins are fail-closed and ambiguous.
                raise UnknownOrderStateError("Exchange response was ambiguous; reconciliation required") from exc

    def reconcile(self, order: DemoOrder) -> ExecutionResult | None:
        """Read-only lookup by deterministic client order ID; never submits an order."""
        self._validate_live_gate()
        return self.adapter.find_order_by_client_id(order.client_order_id, order.symbol)


class DeterministicDemoExecutionAdapter:
    """Local deterministic simulator; never connects to a venue."""

    mode = ExecutionMode.DEMO

    def validate_account_capabilities(self) -> AccountCapabilities:
        return AccountCapabilities(authenticated=True, can_trade=True, supports_client_order_id=True)

    def submit_order(self, order: DemoOrder) -> ExecutionResult:
        raw = {
            "exchange_order_id": f"demo-ex-{order.client_order_id}",
            "status": OrderStatus.OPEN.value,
            "filled_quantity": "0",
            "fee": "0",
            "demo": True,
        }
        return ExecutionResult(
            exchange_order_id=raw["exchange_order_id"],
            status=OrderStatus.OPEN,
            raw=raw,
        )

    def find_order_by_client_id(self, client_order_id: str, symbol: str) -> ExecutionResult | None:
        return None


class LegacyDemoExecutionAdapter:
    """Compatibility wrapper for existing deterministic test/demo adapters."""

    mode = ExecutionMode.DEMO

    def __init__(self, legacy_adapter: Any) -> None:
        self.legacy_adapter = legacy_adapter

    def validate_account_capabilities(self) -> AccountCapabilities:
        return AccountCapabilities(authenticated=True, can_trade=True, supports_client_order_id=True)

    def submit_order(self, order: DemoOrder) -> ExecutionResult:
        try:
            response = self.legacy_adapter.submit(order)
        except ExecutionError:
            raise
        except Exception as exc:
            raise UnknownOrderStateError("Demo exchange response was ambiguous; reconciliation required") from exc
        return ExecutionResult(
            exchange_order_id=response.get("exchange_order_id"),
            status=OrderStatus(response.get("status", OrderStatus.UNKNOWN.value)),
            filled_quantity=Decimal(str(response.get("filled_quantity", "0"))),
            fee=Decimal(str(response.get("fee", "0"))),
            raw=dict(response),
        )

    def find_order_by_client_id(self, client_order_id: str, symbol: str) -> ExecutionResult | None:
        return None
