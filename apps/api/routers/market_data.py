from security_auth import current_principal
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from database import get_db
from models import OHLCVCandle
from schemas import (
    OHLCVCandleResponse,
    MarketDataSyncRequest,
    MarketDataSyncResponse,
)
from services.market_data import sync_market_data

router = APIRouter(prefix="/v1/market-data", tags=["market-data"], dependencies=[Depends(current_principal)])


@router.get("/ohlcv", response_model=List[OHLCVCandleResponse])
def get_ohlcv(
    exchange: str = Query("binance", max_length=32),
    symbol: str = Query("BTC/USDT", max_length=32),
    timeframe: str = Query("1h", max_length=16),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Read-only endpoint retrieving persisted OHLCV candles from PostgreSQL.
    Stateless endpoint: does not start permanent background fetch loops.
    """
    stmt = (
        select(OHLCVCandle)
        .where(
            OHLCVCandle.exchange == exchange.lower(),
            OHLCVCandle.symbol == symbol,
            OHLCVCandle.timeframe == timeframe,
        )
        .order_by(OHLCVCandle.open_time.asc())
        .limit(limit)
    )
    candles = db.execute(stmt).scalars().all()
    return candles


@router.post(
    "/sync", response_model=MarketDataSyncResponse, status_code=status.HTTP_200_OK
)
def sync_ohlcv(
    request: MarketDataSyncRequest,
    db: Session = Depends(get_db),
):
    """
    Finite manual sync endpoint fetching a single batch of OHLCV candles
    and persisting closed candles without duplicates.
    """
    try:
        res = sync_market_data(
            db=db,
            exchange_id=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            limit=request.limit,
        )
        return res
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Market data sync failed: {str(e)}",
        )
