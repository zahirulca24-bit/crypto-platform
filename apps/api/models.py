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
