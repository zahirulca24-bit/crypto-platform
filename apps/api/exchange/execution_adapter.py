"""CCXT execution adapter for the approved exchange boundary only.

This is the only module that resolves private execution credentials.  It exposes
trade/account primitives required by ExecutionGateway and intentionally exposes
no withdrawal method or withdrawal API.
"""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Mapping

import ccxt

from packages.exchange.execution import (
    AccountCapabilities,
    ExchangeAuthenticationError,
    ExchangeOrderRejectedError,
    ExchangePermissionError,
    ExchangePreflightTimeoutError,
    ExchangeRateLimitError,
    ExecutionMode,
    ExecutionResult,
    SafeToRetrySubmissionError,
    UnknownOrderStateError,
)
from packages.exchange.models import DemoOrder, OrderStatus


class CCXTExecutionAdapter:
    def __init__(
        self,
        *,
        exchange_id: str,
        mode: ExecutionMode | str,
        exchange_instance: Any | None = None,
        credentials: Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout_ms: int = 10_000,
    ) -> None:
        self.exchange_id = exchange_id.lower().strip()
        self.mode = ExecutionMode(mode)
        self.timeout_ms = max(1_000, min(int(timeout_ms), 30_000))
        if exchange_instance is not None:
            self.exchange = exchange_instance
            return

        if credentials is not None:
            api_key = credentials.get("api_key", "")
            api_secret = credentials.get("api_secret", "")
            password = credentials.get("password", "")
        elif self.mode is ExecutionMode.LIVE:
            # Production/live credentials may only come from the encrypted
            # credential store through the approved factory boundary.
            raise ExchangeAuthenticationError("Validated live credential is unavailable")
        else:
            source = os.environ if env is None else env
            # Legacy demo-only environment support remains for Phase 0-4
            # compatibility. Production/live never reads plaintext env keys.
            api_key = source.get("DEMO_API_KEY", "")
            api_secret = source.get("DEMO_API_SECRET", "")
            password = source.get("DEMO_API_PASSWORD", "")

        exchange_class = getattr(ccxt, self.exchange_id, None)
        if exchange_class is None:
            raise ValueError("Unsupported exchange adapter")
        config: dict[str, Any] = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "timeout": self.timeout_ms,
            "options": {"defaultType": "spot"},
        }
        if password:
            config["password"] = password
        self.exchange = exchange_class(config)
        if self.mode is ExecutionMode.DEMO:
            if not hasattr(self.exchange, "set_sandbox_mode"):
                raise ValueError("Selected exchange does not expose sandbox mode")
            self.exchange.set_sandbox_mode(True)

    @staticmethod
    def _has(exchange: Any, capability: str) -> bool:
        value = getattr(exchange, "has", {}).get(capability)
        return bool(value)

    def validate_account_capabilities(self) -> AccountCapabilities:
        try:
            self.exchange.load_markets()
            # Authenticated, read-only check. No order and no withdrawal operation.
            self.exchange.fetch_balance()
        except ccxt.AuthenticationError as exc:
            raise ExchangeAuthenticationError("Exchange authentication failed") from exc
        except ccxt.PermissionDenied as exc:
            raise ExchangePermissionError("Exchange account permissions do not allow trading checks") from exc
        except ccxt.RateLimitExceeded as exc:
            raise ExchangeRateLimitError("Exchange rate limit reached during account validation") from exc
        except (ccxt.RequestTimeout, ccxt.NetworkError) as exc:
            raise ExchangePreflightTimeoutError("Exchange account validation timed out") from exc
        except ccxt.ExchangeError as exc:
            raise ExchangeOrderRejectedError("Exchange rejected account validation") from exc

        can_trade = self._has(self.exchange, "createOrder")
        supports_client_id = self._has(self.exchange, "fetchOrderByClientOrderId") or self._has(self.exchange, "fetchOpenOrders")
        reasons: list[str] = []
        if not can_trade:
            reasons.append("create_order_unsupported")
        if not supports_client_id:
            reasons.append("client_order_lookup_unsupported")
        return AccountCapabilities(
            authenticated=True,
            can_trade=can_trade,
            supports_client_order_id=supports_client_id,
            spot_enabled=True,
            reason_codes=tuple(reasons),
        )

    def submit_order(self, order: DemoOrder) -> ExecutionResult:
        params = {"clientOrderId": order.client_order_id}
        price = None if order.type.value == "market" else float(order.price)
        try:
            response = self.exchange.create_order(
                order.symbol,
                order.type.value,
                order.side.lower(),
                float(order.quantity),
                price,
                params,
            )
        except ccxt.AuthenticationError as exc:
            raise ExchangeAuthenticationError("Exchange authentication failed") from exc
        except ccxt.PermissionDenied as exc:
            raise ExchangePermissionError("Exchange account is not permitted to place this order") from exc
        except ccxt.InvalidOrder as exc:
            raise ExchangeOrderRejectedError("Exchange rejected the order") from exc
        except ccxt.InsufficientFunds as exc:
            raise ExchangeOrderRejectedError("Exchange rejected the order for insufficient funds") from exc
        except ccxt.RateLimitExceeded as exc:
            # A CCXT rate-limit exception does not prove the request was never accepted.
            raise UnknownOrderStateError("Order submission was rate-limited with ambiguous venue state") from exc
        except (ccxt.RequestTimeout, ccxt.NetworkError) as exc:
            raise UnknownOrderStateError("Order submission response timed out; reconciliation required") from exc
        except ccxt.ExchangeNotAvailable as exc:
            raise UnknownOrderStateError("Exchange became unavailable during submission; reconciliation required") from exc
        except ccxt.ExchangeError as exc:
            raise ExchangeOrderRejectedError("Exchange rejected the order") from exc
        except Exception as exc:
            raise UnknownOrderStateError("Unexpected exchange response; reconciliation required") from exc

        return self._normalize_order(response)

    def find_order_by_client_id(self, client_order_id: str, symbol: str) -> ExecutionResult | None:
        try:
            if self._has(self.exchange, "fetchOrderByClientOrderId"):
                response = self.exchange.fetch_order_by_client_order_id(client_order_id, symbol)
                return self._normalize_order(response) if response else None
            if self._has(self.exchange, "fetchOpenOrders"):
                for row in self.exchange.fetch_open_orders(symbol):
                    if str(row.get("clientOrderId") or row.get("clientOrderID") or "") == client_order_id:
                        return self._normalize_order(row)
                if self._has(self.exchange, "fetchClosedOrders"):
                    for row in self.exchange.fetch_closed_orders(symbol):
                        if str(row.get("clientOrderId") or row.get("clientOrderID") or "") == client_order_id:
                            return self._normalize_order(row)
                return None
            raise ExchangePermissionError("Exchange does not support client-order reconciliation")
        except (ccxt.RequestTimeout, ccxt.NetworkError, ccxt.RateLimitExceeded) as exc:
            raise ExchangePreflightTimeoutError("Order reconciliation is temporarily unavailable") from exc
        except ccxt.AuthenticationError as exc:
            raise ExchangeAuthenticationError("Exchange authentication failed") from exc
        except ccxt.PermissionDenied as exc:
            raise ExchangePermissionError("Exchange account cannot reconcile orders") from exc


    def fetch_open_positions(self):
        """Read-only recovery snapshot. Returns None when the venue cannot expose positions safely."""
        if not self._has(self.exchange, "fetchPositions"):
            return None
        from packages.reconciliation.models import ExchangePositionSnapshot
        try:
            rows = self.exchange.fetch_positions()
        except (ccxt.RequestTimeout, ccxt.NetworkError, ccxt.RateLimitExceeded) as exc:
            raise ExchangePreflightTimeoutError("Position reconciliation is temporarily unavailable") from exc
        except ccxt.AuthenticationError as exc:
            raise ExchangeAuthenticationError("Exchange authentication failed") from exc
        except ccxt.PermissionDenied as exc:
            raise ExchangePermissionError("Exchange account cannot reconcile positions") from exc
        result = []
        for row in rows or []:
            contracts = Decimal(str(row.get("contracts") or row.get("positionAmt") or "0"))
            if contracts == 0:
                continue
            side = str(row.get("side") or ("long" if contracts > 0 else "short")).lower()
            result.append(ExchangePositionSnapshot(symbol=str(row.get("symbol")), side=side, quantity=abs(contracts)))
        return result

    @staticmethod
    def _normalize_order(response: Mapping[str, Any]) -> ExecutionResult:
        status_map = {
            "open": OrderStatus.OPEN,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELED,
            "cancelled": OrderStatus.CANCELED,
            "rejected": OrderStatus.REJECTED,
        }
        raw_status = str(response.get("status") or "").lower()
        status = status_map.get(raw_status, OrderStatus.UNKNOWN)
        filled = Decimal(str(response.get("filled") or "0"))
        remaining = Decimal(str(response.get("remaining") or "0"))
        if status is OrderStatus.OPEN and filled > 0 and remaining > 0:
            status = OrderStatus.PARTIALLY_FILLED
        fee_obj = response.get("fee") or {}
        fee = fee_obj.get("cost", 0) if isinstance(fee_obj, Mapping) else 0
        # Whitelist only non-secret execution fields; never persist/log complete CCXT payloads.
        safe_raw = {
            "id": response.get("id"),
            "clientOrderId": response.get("clientOrderId") or response.get("clientOrderID"),
            "status": raw_status or None,
            "symbol": response.get("symbol"),
            "side": response.get("side"),
            "type": response.get("type"),
            "filled": response.get("filled"),
            "remaining": response.get("remaining"),
        }
        return ExecutionResult(
            exchange_order_id=str(response.get("id")) if response.get("id") is not None else None,
            status=status,
            filled_quantity=filled,
            fee=Decimal(str(fee or "0")),
            raw=safe_raw,
        )
