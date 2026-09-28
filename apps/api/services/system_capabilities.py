"""Configuration-level readiness/capability reporting without secret disclosure."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from settings import AppSettings, RuntimeMode, TradingMode


class UnavailableReason(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    message: str


class CapabilityState(BaseModel):
    enabled: bool
    reasons: list[UnavailableReason] = Field(default_factory=list)


class SystemCapabilities(BaseModel):
    runtime_mode: RuntimeMode
    trading_mode: TradingMode
    capabilities: dict[str, CapabilityState]


class ReadinessCheck(BaseModel):
    ready: bool
    reasons: list[UnavailableReason] = Field(default_factory=list)


class SystemReadiness(BaseModel):
    status: str
    runtime_mode: RuntimeMode
    trading_mode: TradingMode
    checks: dict[str, ReadinessCheck]


class CapabilitiesService:
    def __init__(self, settings: AppSettings):
        self.settings = settings

    @staticmethod
    def _state(enabled: bool, *reasons: tuple[str, str]) -> CapabilityState:
        return CapabilityState(
            enabled=enabled,
            reasons=[] if enabled else [UnavailableReason(code=code, message=message) for code, message in reasons],
        )

    def capabilities(self) -> SystemCapabilities:
        s = self.settings
        demo_enabled = s.trading_mode is TradingMode.DEMO
        trading_disabled = s.trading_mode is TradingMode.DISABLED
        live_enabled = (
            s.trading_mode is TradingMode.LIVE
            and s.runtime_mode is RuntimeMode.PRODUCTION
            and s.allow_live_trading
            and bool(s.live_exchange_id)
            and not s.validation_reasons()
        )
        return SystemCapabilities(
            runtime_mode=s.runtime_mode,
            trading_mode=s.trading_mode,
            capabilities={
                "research": self._state(True),
                "strategy_proposals": self._state(True),
                "risk_evaluation": self._state(True),
                "demo_order_execution": self._state(
                    demo_enabled,
                    ("trading_mode_disabled", "Trading is disabled by configuration") if trading_disabled else ("demo_mode_not_selected", "Demo order execution requires trading_mode=demo"),
                ),
                "live_order_execution": self._state(
                    live_enabled,
                    ("live_trading_safety_gates_closed", "Live order execution requires production mode, explicit enablement, a configured exchange, and valid production settings"),
                ),
                "direct_strategy_exchange_orders": self._state(False, ("governance_forbids_direct_execution", "Strategies may only produce StrategyOrderProposal objects for Risk Engine and Order Engine governance")),
                "persistent_fastapi_trading_loop": self._state(False, ("workers_required", "Long-running trading work belongs in supervised workers, not FastAPI")),
            },
        )

    def readiness(self) -> SystemReadiness:
        s = self.settings
        config_reasons = s.validation_reasons()
        db_ok = s.database_url.lower().startswith(("postgresql://", "postgresql+psycopg2://"))
        redis_ok = s.redis_url.lower().startswith(("redis://", "rediss://"))
        checks = {
            "configuration": ReadinessCheck(ready=not config_reasons, reasons=[UnavailableReason(code=r.code, message=r.message) for r in config_reasons]),
            "postgresql_authoritative": ReadinessCheck(ready=db_ok, reasons=[] if db_ok else [UnavailableReason(code="postgresql_not_configured", message="PostgreSQL must remain the authoritative datastore")]),
            "coordination_store_configured": ReadinessCheck(ready=redis_ok, reasons=[] if redis_ok else [UnavailableReason(code="redis_not_configured", message="Redis/Valkey coordination URL is not configured")]),
            "risk_order_governance": ReadinessCheck(ready=True),
            "stateless_api_contract": ReadinessCheck(ready=True),
        }
        ready = all(item.ready for item in checks.values())
        return SystemReadiness(status="ready" if ready else "not_ready", runtime_mode=s.runtime_mode, trading_mode=s.trading_mode, checks=checks)
