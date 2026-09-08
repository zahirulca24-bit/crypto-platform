import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    String,
    Text,
    Integer,
    Boolean,
    LargeBinary,
    DateTime,
    Numeric,
    JSON,
    ForeignKey,
    CheckConstraint,
    UniqueConstraint,
    Index,
    text,
    func,
)
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from database import Base


class User(Base):
    __tablename__ = "users"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'locked', 'disabled')",
            name="ck_users_status",
        ),
        CheckConstraint(
            "failed_login_count >= 0",
            name="ck_users_failed_login_count",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(
        String(320),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    display_name: Mapped[Optional[str]] = mapped_column(
        String(120),
        nullable=True,
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="UTC",
        default="UTC",
    )
    base_currency: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="USDT",
        default="USDT",
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default="active",
        default="active",
    )
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        default=0,
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )
    mfa_secret_encrypted: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class OHLCVCandle(Base):
    __tablename__ = "ohlcv_candles"

    __table_args__ = (
        UniqueConstraint(
            "exchange",
            "symbol",
            "timeframe",
            "open_time",
            name="uq_ohlcv_candle",
        ),
        Index("ix_ohlcv_query", "exchange", "symbol", "timeframe", "open_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    exchange: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    timeframe: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    open_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    open: Mapped[Decimal] = mapped_column(
        Numeric(24, 10),
        nullable=False,
    )
    high: Mapped[Decimal] = mapped_column(
        Numeric(24, 10),
        nullable=False,
    )
    low: Mapped[Decimal] = mapped_column(
        Numeric(24, 10),
        nullable=False,
    )
    close: Mapped[Decimal] = mapped_column(
        Numeric(24, 10),
        nullable=False,
    )
    volume: Mapped[Decimal] = mapped_column(
        Numeric(24, 10),
        nullable=False,
    )
    is_closed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SymbolSelectionRun(Base):
    """
    Persists the configuration and summary counts for each symbol-selection run.
    Stores weights, lookback, winsorization percentiles, and target_volatility
    so every run is fully reproducible for Phase-3 R&D analysis.
    """
    __tablename__ = "symbol_selection_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    # Full request payload + all server-controlled constants
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Fixed scoring weights used for this run
    weights: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Volatility lookback (number of closed candles)
    lookback: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    # Volatility suitability parameters
    target_volatility: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    volatility_tolerance: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    # Winsorization clip percentiles e.g. {"low": 0.01, "high": 0.99}
    winsor_percentiles: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Run-level counts
    scanned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SymbolSelectionResult(Base):
    """
    Persists per-symbol results for each selection run.
    Stores raw metrics, normalized metrics, score components, final score,
    rank, selected/rejected status, and rejection reasons for full R&D traceability.
    """
    __tablename__ = "symbol_selection_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("symbol_selection_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 10), nullable=True)
    # Calculated metrics before any normalization
    raw_metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Metrics after winsorization + min-max scaling
    norm_metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Weighted contribution of each metric to the final score
    score_components: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Machine-readable rejection reason list ([] for selected symbols)
    rejection_reasons: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

class StrategyDecision(Base):
    __tablename__ = 'strategy_decisions'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text('gen_random_uuid()')
    )
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    candle_open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    indicator_values: Mapped[dict] = mapped_column(JSON, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    proposal: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            'exchange',
            'symbol',
            'timeframe',
            'candle_open_time',
            'strategy_name',
            'strategy_version',
            'configuration_hash',
            name='uq_strategy_decision',
        ),
    )

class RiskDecisionModel(Base):
    __tablename__ = 'risk_decisions'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    decision_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class DemoOrderModel(Base):
    __tablename__ = 'demo_orders'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    risk_decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    order_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class PositionModel(Base):
    __tablename__ = 'positions'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    position_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class AppliedOrderFillModel(Base):
    __tablename__ = 'applied_order_fills'
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    position_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class PositionProtectionModel(Base):
    __tablename__ = 'position_protections'
    position_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    protection_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class BotRuntimeStateModel(Base):
    __tablename__ = 'bot_runtime_state'
    bot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False)

class BotCommandModel(Base):
    __tablename__ = 'bot_commands'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    command_json: Mapped[dict] = mapped_column(JSON, nullable=False)

class BotJournalModel(Base):
    __tablename__ = 'bot_journal'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ResearchObservation(Base):
    """Append-only R&D observation of authoritative trading/market activity."""

    __tablename__ = "research_observations"
    __table_args__ = (
        Index("ix_research_observations_event_time", "event_type", "observed_at", "event_id"),
        Index("ix_research_observations_symbol_time", "symbol", "observed_at", "event_id"),
        Index("ix_research_observations_strategy_time", "strategy_name", "observed_at", "event_id"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    timeframe: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    bot_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    strategy_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    strategy_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    strategy_config_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    candle_open_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    volume: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    spread: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    volatility: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    indicator_values: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    selection_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    selection_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    selection_reasons: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    side: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    entry_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    exit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    notional: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    take_profit: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    stop_loss: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    fees: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    slippage: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    realized_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    unrealized_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    holding_time_seconds: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 6), nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    mae: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    mfe: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)

    strategy_decision: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    strategy_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_approved: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    risk_rejection_reasons: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    order_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    protection_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reconciliation_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    market_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    trade_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    decision_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class MarketFeatureSnapshot(Base):
    """Deterministic, read-only research feature snapshot derived from persisted closed candles."""

    __tablename__ = "market_feature_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "exchange", "symbol", "timeframe", "candle_open_time",
            "feature_version", "configuration_hash",
            name="uq_market_feature_snapshot",
        ),
        Index("ix_market_feature_lookup", "symbol", "timeframe", "feature_version", "candle_open_time", "id"),
        Index("ix_market_feature_exchange_time", "exchange", "candle_open_time", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    candle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ohlcv_candles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    observation_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("research_observations.event_id", ondelete="SET NULL"), nullable=True, index=True
    )
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    candle_open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    return_1: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    log_return_1: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    rolling_return: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    rolling_volume: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    volatility: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    true_range: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    atr: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    spread: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    quote_volume: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)

    sma_fast: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    sma_slow: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    ema_fast: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    ema_slow: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    moving_average_distance: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    moving_average_slope: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    price_vs_sma_fast: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    price_vs_sma_slow: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    price_vs_ema_fast: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    price_vs_ema_slow: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)

    rsi: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    macd: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    macd_signal: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    macd_histogram: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    momentum: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)

    candle_body_size: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    upper_wick: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    lower_wick: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    candle_range: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    range_percentile: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    rolling_high_distance: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    rolling_low_distance: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)

    liquidity: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    spread_quality: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    volatility_suitability: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    activity: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    selection_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    selection_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    rejection_reasons: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    selection_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    extra_features: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class MarketRegimeSnapshot(Base):
    """Deterministic research-only regime classification from a persisted feature snapshot."""

    __tablename__ = "market_regime_snapshots"
    __table_args__ = (
        UniqueConstraint("feature_snapshot_id", "regime_version", "configuration_hash", name="uq_market_regime_snapshot"),
        Index("ix_market_regime_history", "symbol", "timeframe", "candle_open_time", "id"),
        Index("ix_market_regime_filter", "regime", "candle_open_time", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    feature_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("market_feature_snapshots.id", ondelete="RESTRICT"), nullable=False, index=True)
    observation_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_observations.event_id", ondelete="SET NULL"), nullable=True, index=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    candle_open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    regime: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    regime_version: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    supporting_signals: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    previous_regime: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    current_regime: Mapped[str] = mapped_column(String(32), nullable=False)
    changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.false())
    transition_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class TradeOutcome(Base):
    """Derived, immutable R&D outcome for an authoritative closed Phase-2 position."""

    __tablename__ = "trade_outcomes"
    __table_args__ = (
        UniqueConstraint("source_position_id", "outcome_version", name="uq_trade_outcome_position_version"),
        Index("ix_trade_outcome_history", "symbol", "entry_time", "id"),
        Index("ix_trade_outcome_strategy", "strategy_name", "strategy_version", "entry_time", "id"),
        Index("ix_trade_outcome_regime", "regime_at_entry", "entry_time", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    source_position_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("positions.id", ondelete="RESTRICT"), nullable=False, index=True)
    observation_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_observations.event_id", ondelete="SET NULL"), nullable=True, index=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    bot_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    notional: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    fees: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    slippage: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    holding_time_seconds: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)
    exit_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    tp_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    sl_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    mae: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    mfe: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    return_pct: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    risk_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    r_multiple: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    regime_at_entry: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    regime_at_exit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    entry_feature_snapshot_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("market_feature_snapshots.id", ondelete="SET NULL"), nullable=True)
    exit_feature_snapshot_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("market_feature_snapshots.id", ondelete="SET NULL"), nullable=True)
    entry_regime_snapshot_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("market_regime_snapshots.id", ondelete="SET NULL"), nullable=True)
    exit_regime_snapshot_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("market_regime_snapshots.id", ondelete="SET NULL"), nullable=True)
    outcome_version: Mapped[str] = mapped_column(String(32), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ResearchHypothesis(Base):
    """Deterministic research-only hypothesis derived from persisted R&D evidence."""
    __tablename__ = "research_hypotheses"
    __table_args__ = (
        UniqueConstraint("hypothesis_type", "hypothesis_version", "configuration_hash", name="uq_research_hypothesis_scope"),
        Index("ix_research_hypothesis_filters", "hypothesis_type", "status", "strategy_name", "symbol", "regime", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    hypothesis_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    strategy_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    strategy_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    timeframe: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    regime: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    feature_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    entry_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    exit_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    risk_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    priority_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    hypothesis_version: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_hypothesis_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_hypotheses.id", ondelete="SET NULL"), nullable=True)
    observation_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_observations.event_id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class ResearchExperiment(Base):
    """Deterministic, research-only historical replay/evaluation result."""
    __tablename__ = "research_experiments"
    __table_args__ = (
        UniqueConstraint("hypothesis_id", "experiment_type", "experiment_version", "configuration_hash", name="uq_research_experiment_scope"),
        Index("ix_research_experiment_filters", "experiment_type", "status", "strategy_name", "symbol", "timeframe", "passed", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    hypothesis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_hypotheses.id", ondelete="RESTRICT"), nullable=False, index=True)
    start_observation_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_observations.event_id", ondelete="SET NULL"), nullable=True)
    completion_observation_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_observations.event_id", ondelete="SET NULL"), nullable=True)
    experiment_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    symbol: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    timeframe: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    strategy_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    strategy_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    train_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    train_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validation_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    experiment_version: Mapped[str] = mapped_column(String(32), nullable=False)
    hypothesis_version: Mapped[str] = mapped_column(String(32), nullable=False)
    hypothesis_configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    baseline_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    baseline_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    comparison_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    stability_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    data_quality_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class ResearchCandidateStrategy(Base):
    """Versioned research candidate. Never an executable Phase-2 strategy."""
    __tablename__ = "research_candidate_strategies"
    __table_args__ = (
        UniqueConstraint("source_experiment_id", "candidate_version", "configuration_hash", name="uq_research_candidate_scope"),
        Index("ix_research_candidate_filters", "status", "base_strategy_name", "source_hypothesis_id", "source_experiment_id", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_hypothesis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_hypotheses.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_experiment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_experiments.id", ondelete="RESTRICT"), nullable=False, index=True)
    base_strategy_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    base_strategy_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    candidate_version: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timeframe_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    regime_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    feature_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    entry_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    exit_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    risk_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    parameter_overrides: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evaluation_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    experiment_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    stability_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    data_quality_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_candidate_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_candidate_strategies.id", ondelete="SET NULL"), nullable=True)
    research_observation_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_observations.event_id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CandidatePromotionEvaluation(Base):
    """Deterministic research governance gate result; grants no execution capability."""
    __tablename__ = "candidate_promotion_evaluations"
    __table_args__ = (
        UniqueConstraint("candidate_id", "gate_version", "configuration_hash", name="uq_candidate_promotion_scope"),
        Index("ix_candidate_promotion_candidate_time", "candidate_id", "evaluated_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_candidate_strategies.id", ondelete="CASCADE"), nullable=False, index=True)
    gate_version: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sample_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    expectancy_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    profit_factor_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    drawdown_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    stability_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    data_quality_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    execution_cost_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    regime_robustness_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gate_results: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    failure_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
