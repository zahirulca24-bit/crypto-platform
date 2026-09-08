import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: Optional[str] = Field(None, max_length=120)
    timezone: Optional[str] = Field("UTC", max_length=64)
    base_currency: Optional[str] = Field("USDT", max_length=16)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: Optional[str] = None
    timezone: str
    base_currency: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class OHLCVCandleResponse(BaseModel):
    id: uuid.UUID
    exchange: str
    symbol: str
    timeframe: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    is_closed: bool

    class Config:
        from_attributes = True


class MarketDataSyncRequest(BaseModel):
    exchange: str = Field("binance", max_length=32)
    symbol: str = Field("BTC/USDT", max_length=32)
    timeframe: str = Field("1h", max_length=16)
    limit: int = Field(100, ge=1, le=1000)


class MarketDataSyncResponse(BaseModel):
    exchange: str
    symbol: str
    timeframe: str
    fetched_count: int
    inserted_count: int
    skipped_count: int


class ExchangeCapabilities(BaseModel):
    supports_spot: bool
    supports_futures: bool
    supports_fetch_balance: bool
    supports_fetch_positions: bool
    supports_client_order_ids: bool
    supports_reduce_only: bool
    supports_native_stop_loss: bool
    supports_native_take_profit: bool
    supports_oco: bool


class DemoExchangeVerifyRequest(BaseModel):
    exchange: Optional[str] = Field(None, max_length=32)
    api_key: Optional[str] = Field(None, max_length=256)
    api_secret: Optional[str] = Field(None, max_length=256)
    password: Optional[str] = Field(None, max_length=256)


class DemoExchangeVerifyResponse(BaseModel):
    exchange: str
    environment: str = "demo"
    is_valid: bool
    capabilities: ExchangeCapabilities
    message: str


class BalanceItem(BaseModel):
    currency: str
    free: Decimal
    used: Decimal
    total: Decimal


class PositionItem(BaseModel):
    symbol: str
    side: str
    contracts: Decimal
    entry_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None


class DemoAccountSummaryResponse(BaseModel):
    exchange: str
    environment: str = "demo"
    balances: list[BalanceItem]
    positions: list[PositionItem]
    capabilities: ExchangeCapabilities



# ── Symbol Selection ────────────────────────────────────────────────────────

class SymbolSelectionRequest(BaseModel):
    exchange: str = Field(..., max_length=32, description="Exchange ID (e.g. 'binance')")
    quote_currency: Optional[str] = Field(None, max_length=16, description="Filter by quote currency (e.g. 'USDT')")
    market_type: Optional[str] = Field(None, description="'spot' or 'future'")
    max_symbols: Optional[int] = Field(10, ge=1, le=500, description="Maximum symbols to select (default 10)")
    min_quote_volume: Optional[float] = Field(None, ge=0, description="Minimum 24h quote volume")
    max_spread_pct: Optional[float] = Field(None, ge=0, description="Maximum spread as % of mid-price")
    min_volatility: Optional[float] = Field(None, ge=0, description="Minimum volatility (log-return std-dev)")
    max_volatility: Optional[float] = Field(None, ge=0, description="Maximum volatility (log-return std-dev)")
    include_symbols: Optional[List[str]] = Field(None, description="Only consider these symbols")
    exclude_symbols: Optional[List[str]] = Field(None, description="Explicitly exclude these symbols")


class SymbolMetrics(BaseModel):
    last_price: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread_pct: Optional[float] = None        # (ask-bid)/mid*100
    quote_volume_24h: Optional[float] = None  # raw 24h quote volume
    base_volume_24h: Optional[float] = None
    volatility: Optional[float] = None        # std-dev of log-returns
    percent_change: Optional[float] = None    # (last - open) / open * 100
    activity: Optional[float] = None          # 1.0 for active markets


class NormalizedMetrics(BaseModel):
    liquidity: Optional[float] = None   # min-max of log10(quote_volume) after winsorization
    spread: Optional[float] = None
    volatility: Optional[float] = None
    activity: Optional[float] = None


class ScoreComponents(BaseModel):
    liquidity: float = 0.0             # 0.40 * norm_liquidity
    spread: float = 0.0                # 0.30 * (1 - norm_spread)
    volatility: float = 0.0            # 0.20 * volatility_suitability
    activity: float = 0.0              # 0.10 * norm_activity
    volatility_suitability: float = 0.0  # intermediate value for R&D traceability


class SymbolSelectionResultItem(BaseModel):
    symbol: str
    selected: bool
    rank: Optional[int] = None
    score: Optional[float] = None
    metrics: SymbolMetrics
    normalized_metrics: NormalizedMetrics
    score_components: ScoreComponents
    rejection_reasons: Optional[List[str]] = None

    class Config:
        from_attributes = True


class SymbolSelectionResponse(BaseModel):
    run_id: str
    exchange: str
    scanned_count: int
    eligible_count: int
    selected_count: int
    rejected_count: int
    selected_symbols: List[str]
    results: List[SymbolSelectionResultItem]

class OrderProposal(BaseModel):
    action: str
    sizing_intent: str = 'risk_engine_default'

class StrategyDecisionResponse(BaseModel):
    id: uuid.UUID
    exchange: str
    symbol: str
    timeframe: str
    candle_open_time: datetime
    strategy_name: str
    strategy_version: str
    configuration: dict
    configuration_hash: str
    indicator_values: dict
    decision: str
    proposal: Optional[OrderProposal]
    reason: str
    created_at: datetime
    
class StrategyEvaluateRequest(BaseModel):
    exchange: str
    symbol: str
    timeframe: str
