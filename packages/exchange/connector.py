from abc import ABC, abstractmethod
from typing import List, Dict, Any


class MarketDataConnector(ABC):
    """Abstract interface for public market data exchange connectors."""

    @abstractmethod
    def fetch_markets(self) -> List[Dict[str, Any]]:
        """Fetch list of supported markets/symbols."""
        pass

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """Fetch current public ticker for a symbol."""
        pass

    @abstractmethod
    def fetch_ohlcv(
        self, symbol: str, timeframe: str = "1h", limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV candlestick data for a symbol.
        Returns list of dicts with keys:
        [exchange, symbol, timeframe, open_time, open, high, low, close, volume, is_closed]
        """
        pass


class AuthenticatedExchangeConnector(ABC):
    """Abstract interface for authenticated exchange connectors (Demo & Live)."""

    @abstractmethod
    def verify_credentials(self) -> bool:
        """Verify API key and secret credentials with exchange."""
        pass

    @abstractmethod
    def fetch_balance(self) -> Dict[str, Any]:
        """Fetch account balance details."""
        pass

    @abstractmethod
    def fetch_open_orders(self, symbol: str | None = None) -> List[Dict[str, Any]]:
        """Fetch currently open orders."""
        pass

    @abstractmethod
    def fetch_closed_orders(
        self, symbol: str | None = None, since: int | None = None
    ) -> List[Dict[str, Any]]:
        """Fetch historical closed/canceled orders."""
        pass

    @abstractmethod
    def fetch_my_trades(
        self, symbol: str | None = None, since: int | None = None
    ) -> List[Dict[str, Any]]:
        """Fetch account trades execution history."""
        pass

    @abstractmethod
    def fetch_positions(
        self, symbols: List[str] | None = None
    ) -> List[Dict[str, Any]]:
        """Fetch open positions (if exchange/account supports positions)."""
        pass

    @abstractmethod
    def fetch_exchange_time(self) -> int:
        """Fetch current exchange server timestamp in milliseconds."""
        pass

    @abstractmethod
    def load_markets(self) -> Dict[str, Any]:
        """Load exchange market definitions."""
        pass

