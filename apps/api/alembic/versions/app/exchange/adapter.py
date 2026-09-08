from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from decimal import Decimal
import ccxt

from exchange.connector import MarketDataConnector


class CCXTMarketDataAdapter(MarketDataConnector):
    """
    Public market data adapter using CCXT.
    Strictly public market data endpoints only.
    No private credentials, account endpoints, or order submissions.
    """

    SUPPORTED_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"}

    def __init__(
        self,
        exchange_id: str = "kraken",
        exchange_instance: Optional[ccxt.Exchange] = None,
    ):
        self.exchange_id = exchange_id.lower()
        if exchange_instance:
            self.exchange = exchange_instance
        else:
            exchange_class = getattr(ccxt, self.exchange_id, None)
            if not exchange_class:
                raise ValueError(f"Unsupported exchange: '{exchange_id}'")
            self.exchange = exchange_class(
                {
                    "enableRateLimit": True,
                    "timeout": 10000,
                    "options": {"defaultType": "spot"},
                }
            )

    def fetch_markets(self) -> List[Dict[str, Any]]:
        try:
            markets = self.exchange.load_markets()
            return [
                {
                    "symbol": symbol,
                    "base": market.get("base"),
                    "quote": market.get("quote"),
                    "active": market.get("active", True),
                }
                for symbol, market in markets.items()
            ]
        except Exception as e:
            raise RuntimeError(
                f"Failed to fetch markets from {self.exchange_id}: {str(e)}"
            )

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        if not symbol or not isinstance(symbol, str) or "/" not in symbol:
            raise ValueError(f"Invalid symbol format: '{symbol}'")
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return {
                "symbol": symbol,
                "last": (
                    Decimal(str(ticker["last"]))
                    if ticker.get("last") is not None
                    else None
                ),
                "bid": (
                    Decimal(str(ticker["bid"]))
                    if ticker.get("bid") is not None
                    else None
                ),
                "ask": (
                    Decimal(str(ticker["ask"]))
                    if ticker.get("ask") is not None
                    else None
                ),
                "volume": (
                    Decimal(str(ticker["baseVolume"]))
                    if ticker.get("baseVolume") is not None
                    else None
                ),
                "timestamp": ticker.get("timestamp"),
            }
        except ccxt.BadSymbol as e:
            raise ValueError(
                f"Invalid symbol '{symbol}' for exchange '{self.exchange_id}': {str(e)}"
            )
        except ccxt.NetworkError as e:
            raise RuntimeError(
                f"Network error connecting to {self.exchange_id}: {str(e)}"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to fetch ticker for {symbol}: {str(e)}")

    def fetch_ohlcv(
        self, symbol: str, timeframe: str = "1h", limit: int = 100
    ) -> List[Dict[str, Any]]:
        if not symbol or not isinstance(symbol, str) or "/" not in symbol:
            raise ValueError(f"Invalid symbol format: '{symbol}'")

        if timeframe not in self.SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}'. Must be one of {sorted(self.SUPPORTED_TIMEFRAMES)}"
            )

        if limit < 1 or limit > 1000:
            raise ValueError("Limit must be between 1 and 1000")

        try:
            raw_ohlcv = self.exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, limit=limit
            )
        except ccxt.BadSymbol as e:
            raise ValueError(
                f"Invalid symbol '{symbol}' for exchange '{self.exchange_id}': {str(e)}"
            )
        except ccxt.NetworkError as e:
            raise RuntimeError(
                f"Network error connecting to {self.exchange_id}: {str(e)}"
            )
        except ccxt.ExchangeError as e:
            raise ValueError(
                f"Exchange error from {self.exchange_id}: {str(e)}"
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to fetch OHLCV from {self.exchange_id}: {str(e)}"
            )

        parsed_candles = []
        for i, item in enumerate(raw_ohlcv):
            timestamp_ms, open_val, high_val, low_val, close_val, volume_val = item
            open_dt = datetime.fromtimestamp(
                timestamp_ms / 1000.0, tz=timezone.utc
            )
            is_closed = i < len(raw_ohlcv) - 1

            parsed_candles.append(
                {
                    "exchange": self.exchange_id,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open_time": open_dt,
                    "open": Decimal(str(open_val)),
                    "high": Decimal(str(high_val)),
                    "low": Decimal(str(low_val)),
                    "close": Decimal(str(close_val)),
                    "volume": Decimal(str(volume_val)),
                    "is_closed": is_closed,
                }
            )

        return parsed_candles
