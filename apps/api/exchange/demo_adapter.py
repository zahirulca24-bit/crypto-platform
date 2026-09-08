from typing import List, Dict, Any, Optional
import ccxt

from exchange.connector import AuthenticatedExchangeConnector


class CCXTDemoExchangeAdapter(AuthenticatedExchangeConnector):
    """
    Authenticated Demo Exchange Adapter using CCXT.
    Enforces DEMO / SANDBOX mode execution with safety guards.
    Strictly read-only operations for account info, balance, and order/position query.
    No order placement or execution features are exposed or implemented.
    """

    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        password: Optional[str] = None,
        is_demo: bool = True,
        exchange_instance: Optional[ccxt.Exchange] = None,
    ):
        self.exchange_id = exchange_id.lower()
        self.is_demo = is_demo

        # Explicit Safety Guard
        if not self.is_demo:
            raise ValueError(
                "Production mode rejected: Demo exchange connector must run in sandbox/demo mode only."
            )

        if exchange_instance:
            self.exchange = exchange_instance
        else:
            exchange_class = getattr(ccxt, self.exchange_id, None)
            if not exchange_class:
                raise ValueError(f"Unsupported exchange: '{exchange_id}'")

            config: Dict[str, Any] = {
                "apiKey": api_key or "",
                "secret": api_secret or "",
                "enableRateLimit": True,
                "timeout": 10000,
            }
            if password:
                config["password"] = password

            self.exchange = exchange_class(config)

        # Force and verify Sandbox / Demo Mode
        try:
            if hasattr(self.exchange, "set_sandbox_mode"):
                self.exchange.set_sandbox_mode(True)
        except Exception as e:
            raise RuntimeError(
                f"Production mode rejected: Failed to set sandbox mode for exchange '{self.exchange_id}'. Error: {str(e)}"
            )

    def __repr__(self) -> str:
        api_key_masked = (
            f"{self.exchange.apiKey[:4]}***" if self.exchange.apiKey else "None"
        )
        return (
            f"<CCXTDemoExchangeAdapter exchange={self.exchange_id} "
            f"environment=demo apiKey={api_key_masked}>"
        )

    def _sanitize_error(self, exc: Exception) -> str:
        """Strip sensitive secrets or credentials from error message strings."""
        msg = str(exc)
        if self.exchange.secret and self.exchange.secret in msg:
            msg = msg.replace(self.exchange.secret, "***MASKED_SECRET***")
        if self.exchange.apiKey and self.exchange.apiKey in msg:
            msg = msg.replace(self.exchange.apiKey, "***MASKED_KEY***")
        return msg

    def get_capabilities(self) -> Dict[str, bool]:
        """Detect and return structured capability indicators."""
        has_dict = getattr(self.exchange, "has", {}) or {}
        options = getattr(self.exchange, "options", {}) or {}

        supports_spot = bool(has_dict.get("fetchBalance", True))
        supports_futures = bool(
            has_dict.get("fetchPositions", False)
            or options.get("defaultType") in ("future", "swap")
        )
        supports_fetch_balance = bool(has_dict.get("fetchBalance", False))
        supports_fetch_positions = bool(has_dict.get("fetchPositions", False))
        supports_client_order_ids = bool(has_dict.get("createOrder", False))

        has_str = str(has_dict)
        supports_reduce_only = "reduceOnly" in has_str or "reduce_only" in has_str
        supports_native_stop_loss = bool(
            has_dict.get("stopLoss", False)
            or "stopLossPrice" in has_str
            or "stopLoss" in has_str
        )
        supports_native_take_profit = bool(
            has_dict.get("takeProfit", False)
            or "takeProfitPrice" in has_str
            or "takeProfit" in has_str
        )
        supports_oco = bool(
            has_dict.get("createOCOOrder", False)
            or has_dict.get("OCO", False)
            or "OCO" in has_str
        )

        return {
            "supports_spot": supports_spot,
            "supports_futures": supports_futures,
            "supports_fetch_balance": supports_fetch_balance,
            "supports_fetch_positions": supports_fetch_positions,
            "supports_client_order_ids": supports_client_order_ids,
            "supports_reduce_only": supports_reduce_only,
            "supports_native_stop_loss": supports_native_stop_loss,
            "supports_native_take_profit": supports_native_take_profit,
            "supports_oco": supports_oco,
        }

    def verify_credentials(self) -> bool:
        """
        Safely test API credentials by fetching balance or loading markets.
        Must NOT attempt to place, cancel, or modify orders or funds.
        """
        try:
            self.exchange.load_markets()
            self.exchange.fetch_balance()
            return True
        except ccxt.AuthenticationError as e:
            raise ValueError(f"Credential verification failed: {self._sanitize_error(e)}")
        except ccxt.NetworkError as e:
            raise RuntimeError(f"Network error during verification: {self._sanitize_error(e)}")
        except Exception as e:
            raise ValueError(f"Credential verification failed: {self._sanitize_error(e)}")

    def fetch_balance(self) -> Dict[str, Any]:
        """Fetch balance from exchange."""
        try:
            balance = self.exchange.fetch_balance()
            return balance
        except ccxt.AuthenticationError as e:
            raise ValueError(f"Authentication failed fetching balance: {self._sanitize_error(e)}")
        except Exception as e:
            raise RuntimeError(f"Failed to fetch balance: {self._sanitize_error(e)}")

    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch open orders."""
        try:
            if hasattr(self.exchange, "fetch_open_orders"):
                return self.exchange.fetch_open_orders(symbol)
            return []
        except Exception as e:
            raise RuntimeError(f"Failed to fetch open orders: {self._sanitize_error(e)}")

    def fetch_closed_orders(
        self, symbol: Optional[str] = None, since: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch closed orders."""
        try:
            if hasattr(self.exchange, "fetch_closed_orders"):
                return self.exchange.fetch_closed_orders(symbol, since)
            return []
        except Exception as e:
            raise RuntimeError(f"Failed to fetch closed orders: {self._sanitize_error(e)}")

    def fetch_my_trades(
        self, symbol: Optional[str] = None, since: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch account execution history."""
        try:
            if hasattr(self.exchange, "fetch_my_trades"):
                return self.exchange.fetch_my_trades(symbol, since)
            return []
        except Exception as e:
            raise RuntimeError(f"Failed to fetch my trades: {self._sanitize_error(e)}")

    def fetch_positions(
        self, symbols: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Fetch open positions if supported."""
        try:
            if self.exchange.has.get("fetchPositions"):
                return self.exchange.fetch_positions(symbols)
            return []
        except Exception as e:
            raise RuntimeError(f"Failed to fetch positions: {self._sanitize_error(e)}")

    def fetch_exchange_time(self) -> int:
        """Fetch server timestamp in ms."""
        try:
            return self.exchange.milliseconds()
        except Exception as e:
            raise RuntimeError(f"Failed to fetch exchange time: {self._sanitize_error(e)}")

    def load_markets(self) -> Dict[str, Any]:
        """Load market definitions."""
        try:
            return self.exchange.load_markets()
        except Exception as e:
            raise RuntimeError(f"Failed to load markets: {self._sanitize_error(e)}")
