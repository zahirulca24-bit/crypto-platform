"""Approved construction point for execution gateways.

Callers receive the abstract gateway and never instantiate CCXT directly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Mapping

from .execution import DeterministicDemoExecutionAdapter, ExecutionGateway, ExecutionMode

if TYPE_CHECKING:
    from settings import AppSettings


def build_execution_gateway(
    settings: "AppSettings",
    *,
    credential_resolver: Callable[..., Mapping[str, str]] | None = None,
) -> ExecutionGateway | None:
    mode = settings.trading_mode.value
    if mode == "disabled":
        return None
    if mode == "demo":
        return ExecutionGateway(
            DeterministicDemoExecutionAdapter(),
            mode=ExecutionMode.DEMO,
            runtime_mode=settings.runtime_mode.value,
            allow_live_trading=False,
            max_safe_retries=settings.exchange_max_safe_retries,
            retry_delay_seconds=settings.exchange_retry_delay_seconds,
        )
    if mode == "live":
        # Importing the credential-resolving adapter only at the approved boundary keeps
        # routers, strategy/research code, and frontend code independent of CCXT.
        from exchange.execution_adapter import CCXTExecutionAdapter

        if credential_resolver is None:
            raise RuntimeError("Validated live credential resolver is required")
        credentials = credential_resolver(
            exchange_id=settings.live_exchange_id,
            environment="live",
        )
        adapter = CCXTExecutionAdapter(
            exchange_id=settings.live_exchange_id,
            mode=ExecutionMode.LIVE,
            credentials=credentials,
            timeout_ms=settings.exchange_timeout_ms,
        )
        return ExecutionGateway(
            adapter,
            mode=ExecutionMode.LIVE,
            runtime_mode=settings.runtime_mode.value,
            allow_live_trading=settings.allow_live_trading,
            max_safe_retries=settings.exchange_max_safe_retries,
            retry_delay_seconds=settings.exchange_retry_delay_seconds,
        )
    raise ValueError("Unsupported trading mode")
