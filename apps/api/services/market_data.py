from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models import OHLCVCandle
from exchange.connector import MarketDataConnector
from exchange.adapter import CCXTMarketDataAdapter


def sync_market_data(
    db: Session,
    exchange_id: str = "binance",
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    limit: int = 100,
    adapter: Optional[MarketDataConnector] = None,
) -> Dict[str, Any]:
    """
    Fetches finite batch of OHLCV candles, identifies closed candles,
    and safely persists them to PostgreSQL without duplicates.
    """
    if adapter is None:
        adapter = CCXTMarketDataAdapter(exchange_id=exchange_id)

    candles_data = adapter.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    fetched_count = len(candles_data)

    # Filter closed candles only
    closed_candles = [c for c in candles_data if c["is_closed"]]

    if not closed_candles:
        return {
            "exchange": exchange_id.lower(),
            "symbol": symbol,
            "timeframe": timeframe,
            "fetched_count": fetched_count,
            "inserted_count": 0,
            "skipped_count": fetched_count,
        }

    # PostgreSQL ON CONFLICT DO NOTHING WITH RETURNING to accurately count inserted rows
    stmt = (
        pg_insert(OHLCVCandle)
        .values(closed_candles)
        .on_conflict_do_nothing(constraint="uq_ohlcv_candle")
        .returning(OHLCVCandle.id)
    )

    result = db.execute(stmt)
    inserted_ids = result.scalars().all()
    db.commit()

    inserted_count = len(inserted_ids)
    skipped_count = fetched_count - inserted_count

    return {
        "exchange": exchange_id.lower(),
        "symbol": symbol,
        "timeframe": timeframe,
        "fetched_count": fetched_count,
        "inserted_count": inserted_count,
        "skipped_count": skipped_count,
    }
