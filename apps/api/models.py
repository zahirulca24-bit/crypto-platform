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
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    decision_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class DemoOrderModel(Base):
    __tablename__ = 'demo_orders'
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True)
    risk_decision_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False, unique=True)
    order_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class PositionModel(Base):
    __tablename__ = 'positions'
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    position_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class AppliedOrderFillModel(Base):
    __tablename__ = 'applied_order_fills'
    order_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True)
    position_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class PositionProtectionModel(Base):
    __tablename__ = 'position_protections'
    position_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True)
    protection_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class BotRuntimeStateModel(Base):
    __tablename__ = 'bot_runtime_state'
    bot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False)

class BotCommandModel(Base):
    __tablename__ = 'bot_commands'
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    command_json: Mapped[dict] = mapped_column(JSON, nullable=False)

class BotJournalModel(Base):
    __tablename__ = 'bot_journal'
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True)
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

class AIResearchProposal(Base):
    """Research-only structured AI proposal; never an execution or approval authority."""
    __tablename__ = "ai_research_proposals"
    __table_args__ = (
        UniqueConstraint("proposal_version", "prompt_version", "provider", "model_name", "configuration_hash", name="uq_ai_research_proposal_scope"),
        Index("ix_ai_research_proposal_filters", "provider", "model_name", "proposal_type", "status", "strategy_name", "symbol", "regime", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    proposal_type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    timeframe: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    regime: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    hypothesis_statement: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    feature_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    entry_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    exit_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    risk_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    parameter_suggestions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    supporting_evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    referenced_observation_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    referenced_outcome_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    referenced_hypothesis_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    referenced_experiment_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    data_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model_confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 6), nullable=True)
    research_priority: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 6), nullable=True)
    raw_model_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated")
    proposal_version: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    converted_hypothesis_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_hypotheses.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class AIResearchRun(Base):
    """A bounded, research-only AI orchestration run."""
    __tablename__ = "ai_research_runs"
    __table_args__ = (
        Index("ix_ai_research_run_filters", "run_type", "status", "provider", "model_name", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    run_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    orchestrator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timeframe_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    regime_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    strategy_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    data_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    data_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    context_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    proposals_requested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proposals_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proposals_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proposals_suppressed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proposals_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class AIProposalReview(Base):
    """Deterministic review of an AI proposal; scores are not model probabilities."""
    __tablename__ = "ai_proposal_reviews"
    __table_args__ = (
        UniqueConstraint("proposal_id", "research_run_id", "review_version", "configuration_hash", name="uq_ai_proposal_review_scope"),
        Index("ix_ai_proposal_review_run_score", "research_run_id", "overall_score", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_research_proposals.id", ondelete="CASCADE"), nullable=False, index=True)
    research_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_research_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    review_version: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    novelty_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    testability_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    data_quality_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    safety_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    overall_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    accepted_for_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rejection_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    review_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AIStrategyBlueprint(Base):
    """Non-executable AI research strategy blueprint."""
    __tablename__ = "ai_strategy_blueprints"
    __table_args__=(UniqueConstraint("blueprint_version","prompt_version","configuration_hash",name="uq_ai_strategy_blueprint_scope"),Index("ix_ai_strategy_blueprint_filters","blueprint_type","status","base_strategy_name","estimated_complexity","created_at","id"),)
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=text("gen_random_uuid()"))
    name: Mapped[str]=mapped_column(String(255),nullable=False); description: Mapped[str]=mapped_column(Text,nullable=False)
    blueprint_type: Mapped[str]=mapped_column(String(48),nullable=False); status: Mapped[str]=mapped_column(String(32),nullable=False,default="draft")
    source_ai_proposal_id: Mapped[Optional[uuid.UUID]]=mapped_column(ForeignKey("ai_research_proposals.id",ondelete="SET NULL"),nullable=True,index=True)
    source_review_id: Mapped[Optional[uuid.UUID]]=mapped_column(ForeignKey("ai_proposal_reviews.id",ondelete="SET NULL"),nullable=True,index=True)
    source_hypothesis_id: Mapped[Optional[uuid.UUID]]=mapped_column(ForeignKey("research_hypotheses.id",ondelete="SET NULL"),nullable=True,index=True)
    source_experiment_id: Mapped[Optional[uuid.UUID]]=mapped_column(ForeignKey("research_experiments.id",ondelete="SET NULL"),nullable=True,index=True)
    base_strategy_name: Mapped[Optional[str]]=mapped_column(String(64),nullable=True); base_strategy_version: Mapped[Optional[str]]=mapped_column(String(32),nullable=True)
    symbol_scope: Mapped[list]=mapped_column(JSON,nullable=False,default=list); timeframe_scope: Mapped[list]=mapped_column(JSON,nullable=False,default=list); regime_scope: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    feature_requirements: Mapped[list]=mapped_column(JSON,nullable=False,default=list); indicator_requirements: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    entry_logic: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict); exit_logic: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict); protection_logic: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict); risk_constraints: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    parameter_space: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict); expected_behavior: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict); invalidation_conditions: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    evidence_summary: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict); evidence_scope: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    estimated_complexity: Mapped[str]=mapped_column(String(16),nullable=False); estimated_data_requirements: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    readiness_score: Mapped[Decimal]=mapped_column(Numeric(8,6),nullable=False); warnings: Mapped[list]=mapped_column(JSON,nullable=False,default=list); blocking_reasons: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    provider: Mapped[str]=mapped_column(String(64),nullable=False); model_name: Mapped[str]=mapped_column(String(128),nullable=False); prompt_version: Mapped[str]=mapped_column(String(32),nullable=False); blueprint_version: Mapped[str]=mapped_column(String(32),nullable=False)
    configuration: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict); configuration_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    parent_blueprint_id: Mapped[Optional[uuid.UUID]]=mapped_column(ForeignKey("ai_strategy_blueprints.id",ondelete="SET NULL"),nullable=True,index=True); research_observation_id: Mapped[Optional[uuid.UUID]]=mapped_column(ForeignKey("research_observations.event_id",ondelete="SET NULL"),nullable=True,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now()); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())

class BlueprintValidationRun(Base):
    """Deterministic research-only validation of a non-executable AI strategy blueprint."""
    __tablename__ = "blueprint_validation_runs"
    __table_args__ = (
        UniqueConstraint("blueprint_id", "validation_version", "validation_type", "configuration_hash", name="uq_blueprint_validation_run_scope"),
        Index("ix_blueprint_validation_filters", "validation_type", "status", "passed", "created_at", "id"),
        Index("ix_blueprint_validation_blueprint_time", "blueprint_id", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    blueprint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_strategy_blueprints.id", ondelete="CASCADE"), nullable=False, index=True)
    validation_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    validation_version: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timeframe_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    regime_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    data_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    train_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    train_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validation_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_set: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    parameter_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_results: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    simulated_trade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    train_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    combined_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    robustness_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_cost_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0"))
    stability_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0"))
    data_quality_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0"))
    overfit_risk_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("1"))
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BlueprintSimulatedTrade(Base):
    """Research simulation only; intentionally separate from orders/fills/positions/TradeOutcome."""
    __tablename__ = "blueprint_simulated_trades"
    __table_args__ = (
        Index("ix_blueprint_sim_trade_run_time", "validation_run_id", "entry_time", "id"),
        Index("ix_blueprint_sim_trade_scope", "blueprint_id", "symbol", "timeframe", "entry_time", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    validation_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("blueprint_validation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    blueprint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_strategy_blueprints.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    return_pct: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    simulated_fees: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    simulated_slippage: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    mae: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    mfe: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    holding_time_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    exit_reason: Mapped[str] = mapped_column(String(48), nullable=False)
    entry_regime: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    exit_regime: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    entry_feature_snapshot_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("market_feature_snapshots.id", ondelete="SET NULL"), nullable=True)
    entry_regime_snapshot_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("market_regime_snapshots.id", ondelete="SET NULL"), nullable=True)
    parameter_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class AIStrategyEvolutionRun(Base):
    """Bounded research-only strategy evolution cycle."""
    __tablename__ = "ai_strategy_evolution_runs"
    __table_args__ = (
        UniqueConstraint("source_blueprint_id", "source_validation_id", "generation_version", "configuration_hash", name="uq_ai_strategy_evolution_run_scope"),
        Index("ix_ai_strategy_evolution_run_filters", "run_type", "status", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    source_blueprint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_strategy_blueprints.id", ondelete="CASCADE"), nullable=False, index=True)
    source_validation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("blueprint_validation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    run_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    generation_version: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_variants: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_variants: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validated_variants: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_variants: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    champion_before: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_variants.id", ondelete="SET NULL"), nullable=True)
    champion_after: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_variants.id", ondelete="SET NULL"), nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AIStrategyVariant(Base):
    """Immutable research-only mutation of an AI strategy blueprint."""
    __tablename__ = "ai_strategy_variants"
    __table_args__ = (
        UniqueConstraint("source_blueprint_id", "generation_version", "configuration_hash", name="uq_ai_strategy_variant_scope"),
        Index("ix_ai_strategy_variant_filters", "variant_type", "status", "generation_method", "complexity", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    source_blueprint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_strategy_blueprints.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_variants.id", ondelete="SET NULL"), nullable=True, index=True)
    source_validation_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("blueprint_validation_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    evolution_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_evolution_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    variant_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    generation_method: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_version: Mapped[str] = mapped_column(String(32), nullable=False)
    variant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timeframe_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    regime_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    feature_requirements: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    indicator_requirements: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    entry_logic: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    exit_logic: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    protection_logic: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    risk_constraints: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    parameter_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    parameter_space_reference: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    mutation_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    changed_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lineage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    complexity: Mapped[str] = mapped_column(String(16), nullable=False)
    estimated_parameter_combinations: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ChampionChallengerComparison(Base):
    """Deterministic research-only comparison of compatible validations."""
    __tablename__ = "champion_challenger_comparisons"
    __table_args__ = (
        UniqueConstraint("source_blueprint_id", "challenger_variant_id", "comparison_version", "configuration_hash", name="uq_ai_champion_challenger_scope"),
        Index("ix_ai_champion_challenger_filters", "decision", "challenger_wins", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    source_blueprint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_strategy_blueprints.id", ondelete="CASCADE"), nullable=False, index=True)
    champion_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_variants.id", ondelete="SET NULL"), nullable=True)
    champion_validation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("blueprint_validation_runs.id", ondelete="CASCADE"), nullable=False)
    challenger_variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_strategy_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    challenger_validation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("blueprint_validation_runs.id", ondelete="CASCADE"), nullable=False)
    comparison_version: Mapped[str] = mapped_column(String(32), nullable=False)
    comparison_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    champion_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    challenger_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    difference_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    performance_score_difference: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    stability_difference: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    drawdown_difference: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    expectancy_difference: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    profit_factor_difference: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    execution_cost_difference: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    overfit_risk_difference: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    challenger_wins: Mapped[bool] = mapped_column(Boolean, nullable=False)
    decision: Mapped[str] = mapped_column(String(48), nullable=False)
    decision_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class StrategyRegimeProfile(Base):
    """Deterministic research-only regime profile for a validated blueprint/variant."""
    __tablename__ = "strategy_regime_profiles"
    __table_args__ = (
        UniqueConstraint("source_type", "blueprint_id", "variant_id", "regime", "profile_version", "configuration_hash", name="uq_strategy_regime_profile_scope"),
        Index("ix_strategy_regime_profile_filters", "regime", "source_type", "compatibility_score", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    blueprint_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_blueprints.id", ondelete="CASCADE"), nullable=True, index=True)
    variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_variants.id", ondelete="CASCADE"), nullable=True, index=True)
    profile_version: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timeframe_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    regime: Mapped[str] = mapped_column(String(48), nullable=False)
    validation_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    simulated_trade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expectancy: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=Decimal("0"))
    profit_factor: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=Decimal("0"))
    win_rate: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=Decimal("0"))
    stability_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    data_quality_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    overfit_risk_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("1"))
    execution_cost_drag: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    regime_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    compatibility_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    strengths: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    weaknesses: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class ResearchStrategyPortfolio(Base):
    """Research simulation portfolio; never capital allocation authority."""
    __tablename__ = "research_strategy_portfolios"
    __table_args__ = (
        UniqueConstraint("portfolio_version", "configuration_hash", name="uq_research_strategy_portfolio_scope"),
        Index("ix_research_strategy_portfolio_filters", "portfolio_type", "status", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    portfolio_version: Mapped[str] = mapped_column(String(32), nullable=False)
    portfolio_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timeframe_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    regime_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_profile_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_blueprint_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_variant_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_validation_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    component_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    allocation_method: Mapped[str] = mapped_column(String(48), nullable=False)
    allocation_weights: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expected_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    diversification_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    correlation_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    concentration_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("1"))
    robustness_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    data_quality_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    readiness_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    blocking_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class ShadowResearchSession(Base):
    """Request-driven, research-only shadow evaluation session; never trading authority."""
    __tablename__ = "shadow_research_sessions"
    __table_args__ = (
        UniqueConstraint("session_version", "configuration_hash", name="uq_shadow_research_session_scope"),
        Index("ix_shadow_research_session_filters", "status", "source_type", "exchange", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    blueprint_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_blueprints.id", ondelete="CASCADE"), nullable=True, index=True)
    variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_variants.id", ondelete="CASCADE"), nullable=True, index=True)
    research_portfolio_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_strategy_portfolios.id", ondelete="SET NULL"), nullable=True, index=True)
    session_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="created")
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timeframe_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    regime_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_convention: Mapped[str] = mapped_column(String(64), nullable=False)
    fee_bps: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    slippage_bps: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_candle_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_candle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    simulated_trade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    observed_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    drift_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    readiness_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    blocking_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ShadowResearchTrade(Base):
    """Research simulation trade produced by shadow processing, isolated from authoritative ledgers."""
    __tablename__ = "shadow_research_trades"
    __table_args__ = (
        UniqueConstraint("session_id", "signal_time", "entry_time", "parameter_set_hash", name="uq_shadow_trade_event"),
        Index("ix_shadow_research_trade_session_time", "session_id", "signal_time", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shadow_research_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    blueprint_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_blueprints.id", ondelete="SET NULL"), nullable=True)
    variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_variants.id", ondelete="SET NULL"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    exit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 12), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False, default=Decimal("0"))
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False, default=Decimal("0"))
    return_pct: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False, default=Decimal("0"))
    simulated_fees: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False, default=Decimal("0"))
    simulated_slippage: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False, default=Decimal("0"))
    mae: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False, default=Decimal("0"))
    mfe: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False, default=Decimal("0"))
    holding_time_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entry_regime: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    exit_regime: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    parameter_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ResearchCandidateHandoff(Base):
    """Controlled Phase-4 to Phase-3 candidate-governance handoff package."""
    __tablename__ = "research_candidate_handoffs"
    __table_args__ = (
        UniqueConstraint("handoff_version", "configuration_hash", name="uq_research_candidate_handoff_scope"),
        Index("ix_research_candidate_handoff_filters", "source_type", "status", "validation_id", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    blueprint_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_blueprints.id", ondelete="SET NULL"), nullable=True, index=True)
    variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_variants.id", ondelete="SET NULL"), nullable=True, index=True)
    validation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("blueprint_validation_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    shadow_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("shadow_research_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    research_portfolio_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_strategy_portfolios.id", ondelete="SET NULL"), nullable=True, index=True)
    handoff_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    strategy_definition: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    parameter_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    symbol_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timeframe_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    regime_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    validation_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    shadow_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    regime_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    portfolio_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    risk_constraints: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    protection_requirements: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    readiness_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    blocking_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_candidate_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_candidate_strategies.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class ResearchMonitoringPolicy(Base):
    """PostgreSQL-authoritative research monitoring policy; enabling it never enables trading."""
    __tablename__ = "research_monitoring_policies"
    __table_args__ = (
        UniqueConstraint("policy_version", "configuration_hash", name="uq_research_monitoring_policy_scope"),
        Index("ix_research_monitoring_policy_filters", "status", "scope_type", "updated_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timeframe_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    regime_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    strategy_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    blueprint_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_blueprints.id", ondelete="SET NULL"), nullable=True, index=True)
    variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_variants.id", ondelete="SET NULL"), nullable=True, index=True)
    research_portfolio_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_strategy_portfolios.id", ondelete="SET NULL"), nullable=True, index=True)
    shadow_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("shadow_research_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    candidate_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_candidate_strategies.id", ondelete="SET NULL"), nullable=True, index=True)
    trigger_rules: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    thresholds: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    minimum_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=21600)
    last_evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ResearchTriggerEvent(Base):
    """Deterministic research trigger. It has no trading/execution status or authority."""
    __tablename__ = "research_trigger_events"
    __table_args__ = (
        UniqueConstraint("policy_id", "trigger_version", "configuration_hash", name="uq_research_trigger_event_scope"),
        Index("ix_research_trigger_event_filters", "policy_id", "trigger_type", "status", "detected_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    policy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_monitoring_policies.id", ondelete="CASCADE"), nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="detected")
    trigger_version: Mapped[str] = mapped_column(String(32), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    timeframe: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    regime: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    strategy_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_entity_type: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    source_entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    baseline_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    current_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    difference_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    severity_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    evidence_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    trigger_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    research_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("adaptive_research_jobs.id", ondelete="SET NULL", use_alter=True, name="fk_trigger_research_job"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AdaptiveResearchJob(Base):
    """Bounded research job. It may call research services but never trading control services."""
    __tablename__ = "adaptive_research_jobs"
    __table_args__ = (
        UniqueConstraint("job_version", "configuration_hash", name="uq_adaptive_research_job_scope"),
        Index("ix_adaptive_research_job_filters", "status", "job_type", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    trigger_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_trigger_events.id", ondelete="SET NULL"), nullable=True, index=True)
    policy_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_monitoring_policies.id", ondelete="SET NULL"), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    job_version: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    target_pipeline_stage: Mapped[str] = mapped_column(String(48), nullable=False)
    requested_actions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    result_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_entity_ids: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ResearchMonitorWorkerStatus(Base):
    """PostgreSQL heartbeat/status for the supervised research monitor worker."""
    __tablename__ = "research_monitor_worker_status"
    worker_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_cycle_started: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_cycle_completed: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    policies_evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    triggers_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class DemoStrategyManifest(Base):
    """Immutable research/governance data artifact for future explicit Demo runtime consumption."""
    __tablename__ = "demo_strategy_manifests"
    __table_args__ = (
        UniqueConstraint("candidate_id", "manifest_version", "configuration_hash", name="uq_demo_strategy_manifest_scope"),
        Index("ix_demo_strategy_manifest_filters", "candidate_id", "status", "compiled_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_candidate_strategies.id", ondelete="RESTRICT"), nullable=False, index=True)
    promotion_evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_promotion_evaluations.id", ondelete="RESTRICT"), nullable=False)
    handoff_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("research_candidate_handoffs.id", ondelete="SET NULL"), nullable=True)
    source_blueprint_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_blueprints.id", ondelete="SET NULL"), nullable=True)
    source_variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ai_strategy_variants.id", ondelete="SET NULL"), nullable=True)
    source_validation_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("blueprint_validation_runs.id", ondelete="SET NULL"), nullable=True)
    shadow_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("shadow_research_sessions.id", ondelete="SET NULL"), nullable=True)
    manifest_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="compiled")
    strategy_name: Mapped[str] = mapped_column(String(255), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timeframe_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    regime_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    feature_requirements: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    indicator_requirements: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    entry_logic: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    exit_logic: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    protection_logic: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    parameter_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    risk_constraints: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    strategy_protocol_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    shadow_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    governance_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    runtime_requirements: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    runtime_compatibility: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    blocking_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_manifest_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("demo_strategy_manifests.id", ondelete="SET NULL"), nullable=True)
    compiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class StrategyRuntimeCompatibilityCheck(Base):
    """Deterministic compatibility assessment; performs no runtime execution."""
    __tablename__ = "strategy_runtime_compatibility_checks"
    __table_args__ = (
        UniqueConstraint("manifest_id", "check_version", "configuration_hash", name="uq_strategy_runtime_compatibility_scope"),
        Index("ix_strategy_runtime_compatibility_manifest", "manifest_id", "checked_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    manifest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("demo_strategy_manifests.id", ondelete="CASCADE"), nullable=False, index=True)
    check_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    strategy_protocol_compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    feature_compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    indicator_compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    timeframe_compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    market_data_compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    protection_compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    risk_boundary_compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    deterministic_logic_compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    overall_score: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    checks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    blocking_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DemoRuntimeRelease(Base):
    """Governance/runtime handoff artifact only; status=ready does not activate a bot."""
    __tablename__ = "demo_runtime_releases"
    __table_args__ = (
        UniqueConstraint("manifest_id", "release_version", "configuration_hash", name="uq_demo_runtime_release_scope"),
        Index("ix_demo_runtime_release_filters", "candidate_id", "status", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    manifest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("demo_strategy_manifests.id", ondelete="RESTRICT"), nullable=False, index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_candidate_strategies.id", ondelete="RESTRICT"), nullable=False, index=True)
    compatibility_check_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strategy_runtime_compatibility_checks.id", ondelete="RESTRICT"), nullable=False)
    release_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ready")
    release_notes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    governance_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    safety_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
