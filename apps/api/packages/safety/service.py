from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from .models import (
    CircuitBreakerState,
    CircuitBreakerType,
    CircuitBreakerView,
    ControlState,
    HaltMode,
    SafetyAuditEvent,
    SafetyBlocker,
    SafetyCommandResult,
    SafetyHaltRequest,
    SafetyResumeRequest,
    SafetyScope,
    SafetyState,
    SafetyStatus,
)


class SafetyHaltError(RuntimeError):
    code = "safety_halt_active"

    def __init__(self, blockers: list[SafetyBlocker]):
        self.blockers = blockers
        super().__init__("New order execution is blocked by operational safety controls")


class UnsafeResumeError(RuntimeError):
    code = "unsafe_resume_rejected"


class SafetyControlService:
    """Durable operational safety authority for *new entry* execution.

    Severe automatic breakers never auto-close. A healthy observation only marks
    recovery_observed; an explicit audited resume is still required.
    Reconciliation/protective recovery paths intentionally do not call
    ``require_new_entry_allowed``.
    """

    DEFAULT_THRESHOLDS = {
        CircuitBreakerType.EXCHANGE_CONNECTIVITY: 3,
        CircuitBreakerType.EXCESSIVE_ORDER_ERRORS: 5,
        CircuitBreakerType.RECONCILIATION_FAILURE: 3,
        CircuitBreakerType.DRAWDOWN: 1,
        CircuitBreakerType.STALE_MARKET_DATA: 1,
        CircuitBreakerType.CLOCK_DRIFT: 1,
    }

    def __init__(self, store, thresholds: dict[CircuitBreakerType, int] | None = None, incident_reporter=None):
        self.store = store
        self.incident_reporter = incident_reporter
        self.thresholds = dict(self.DEFAULT_THRESHOLDS)
        if thresholds:
            self.thresholds.update(thresholds)

    @staticmethod
    def _validate_scope(scope: SafetyScope, key: str | None) -> None:
        if scope is SafetyScope.GLOBAL and key is not None:
            raise ValueError("Global safety scope must not provide scope_key")
        if scope is not SafetyScope.GLOBAL and not key:
            raise ValueError(f"{scope.value} safety scope requires scope_key")

    def _control(self, state: SafetyState, scope: SafetyScope, key: str | None, create: bool = False):
        self._validate_scope(scope, key)
        if scope is SafetyScope.GLOBAL:
            return state.global_control
        if scope is SafetyScope.BOT:
            if create:
                return state.bots.setdefault(key, ControlState())
            return state.bots.get(key)
        if scope is SafetyScope.SYMBOL:
            if create:
                return state.symbols.setdefault(key.upper(), ControlState())
            return state.symbols.get(key.upper())
        raise ValueError("Circuit scope uses circuit breaker state")

    def status(self, *, bot_id: str | None = None, symbol: str | None = None) -> SafetyStatus:
        state = self.store.load_state()
        blockers = self._blockers(state, bot_id=bot_id, symbol=symbol)
        return SafetyStatus(trading_halted=bool(blockers), blockers=blockers, state=state)

    def _blockers(self, state: SafetyState, *, bot_id: str | None, symbol: str | None) -> list[SafetyBlocker]:
        result: list[SafetyBlocker] = []
        if state.global_control.active:
            result.append(SafetyBlocker(code="global_trading_halted", scope=SafetyScope.GLOBAL, reason_code=state.global_control.reason_code))
        if bot_id:
            c = state.bots.get(bot_id)
            if c and c.active:
                result.append(SafetyBlocker(code=f"bot_{c.mode.value}", scope=SafetyScope.BOT, scope_key=bot_id, reason_code=c.reason_code))
        if symbol:
            c = state.symbols.get(symbol.upper())
            if c and c.active:
                result.append(SafetyBlocker(code="symbol_trading_halted", scope=SafetyScope.SYMBOL, scope_key=symbol.upper(), reason_code=c.reason_code))
        for key, breaker in state.circuits.items():
            if breaker.open:
                result.append(SafetyBlocker(code="circuit_breaker_open", scope=SafetyScope.CIRCUIT, scope_key=key, reason_code=breaker.reason_code))
        return result

    def require_new_entry_allowed(self, *, bot_id: str = "demo-bot", symbol: str) -> None:
        state = self.store.load_state()
        blockers = self._blockers(state, bot_id=bot_id, symbol=symbol)
        if blockers:
            raise SafetyHaltError(blockers)

    def halt(self, request: SafetyHaltRequest) -> SafetyCommandResult:
        self._validate_scope(request.scope, request.scope_key)
        with self.store.locked_state() as state:
            replay = self.store.get_command(request.idempotency_key)
            if replay is not None:
                return SafetyCommandResult.model_validate(replay["result"]).model_copy(update={"idempotent_replay": True})
            now = datetime.now(timezone.utc)
            if request.scope is SafetyScope.CIRCUIT:
                breaker_type = CircuitBreakerType(request.scope_key)
                breaker = self._ensure_breaker(state, breaker_type)
                breaker.open = True
                breaker.reason_code = request.reason_code
                breaker.opened_at = breaker.opened_at or now
                breaker.recovery_observed = False
                active, mode = True, HaltMode.HALTED
            else:
                control = self._control(state, request.scope, request.scope_key, create=True)
                control.active = True
                control.mode = request.mode
                control.reason_code = request.reason_code
                control.activated_at = control.activated_at or now
                control.activated_by = request.operator_id
                active, mode = True, request.mode
            state.updated_at = now
            result = SafetyCommandResult(applied=True, scope=request.scope, scope_key=request.scope_key, active=active, mode=mode, reason_code=request.reason_code)
            self.store.save_state(state)
            self.store.save_command(request.idempotency_key, "halt", request.model_dump(mode="json"), result.model_dump(mode="json"))
            self.store.append_event(SafetyAuditEvent(event_type="safety.halt", scope=request.scope, scope_key=request.scope_key, reason_code=request.reason_code, operator_id=request.operator_id))
            return result

    def resume(self, request: SafetyResumeRequest) -> SafetyCommandResult:
        self._validate_scope(request.scope, request.scope_key)
        with self.store.locked_state() as state:
            replay = self.store.get_command(request.idempotency_key)
            if replay is not None:
                return SafetyCommandResult.model_validate(replay["result"]).model_copy(update={"idempotent_replay": True})
            previous_reason = None
            if request.scope is SafetyScope.CIRCUIT:
                breaker_type = CircuitBreakerType(request.scope_key)
                breaker = self._ensure_breaker(state, breaker_type)
                previous_reason = breaker.reason_code
                if breaker.open and not breaker.recovery_observed:
                    raise UnsafeResumeError("Circuit breaker has no healthy recovery observation")
                breaker.open = False
                breaker.failure_count = 0
                breaker.reason_code = None
                breaker.opened_at = None
                breaker.recovery_observed = False
            else:
                control = self._control(state, request.scope, request.scope_key, create=True)
                previous_reason = control.reason_code
                control.active = False
                control.reason_code = None
                control.activated_at = None
                control.activated_by = None
            state.updated_at = datetime.now(timezone.utc)
            result = SafetyCommandResult(applied=True, scope=request.scope, scope_key=request.scope_key, active=False, reason_code=previous_reason)
            self.store.save_state(state)
            # Store acknowledgement presence/hash-free metadata, not free-form text, to avoid accidental secret persistence.
            safe_request = request.model_dump(mode="json")
            safe_request["acknowledgement"] = "provided"
            self.store.save_command(request.idempotency_key, "resume", safe_request, result.model_dump(mode="json"))
            self.store.append_event(SafetyAuditEvent(event_type="safety.resume", scope=request.scope, scope_key=request.scope_key, reason_code=previous_reason, operator_id=request.operator_id, details={"acknowledgement": "provided"}))
            return result

    def _ensure_breaker(self, state: SafetyState, breaker_type: CircuitBreakerType) -> CircuitBreakerState:
        key = breaker_type.value
        if key not in state.circuits:
            state.circuits[key] = CircuitBreakerState(breaker=breaker_type, threshold=self.thresholds[breaker_type])
        return state.circuits[key]

    def record_failure(self, breaker_type: CircuitBreakerType, *, reason_code: str) -> CircuitBreakerState:
        first_open = False
        result = None
        with self.store.locked_state() as state:
            b = self._ensure_breaker(state, breaker_type)
            now = datetime.now(timezone.utc)
            b.failure_count += 1
            b.last_failure_at = now
            b.last_success_at = None
            b.recovery_observed = False
            if b.failure_count >= b.threshold:
                first_open = not b.open
                b.open = True
                b.reason_code = reason_code
                b.opened_at = b.opened_at or now
                if first_open:
                    self.store.append_event(SafetyAuditEvent(event_type="safety.circuit_opened", scope=SafetyScope.CIRCUIT, scope_key=breaker_type.value, reason_code=reason_code, details={"failure_count": b.failure_count, "threshold": b.threshold}))
            state.updated_at = now
            self.store.save_state(state)
            result = b.model_copy(deep=True)
        # Incident persistence is deliberately outside the safety row-lock transaction.
        # Observability must never commit/alter the authoritative safety transaction.
        if first_open and self.incident_reporter is not None:
            self.incident_reporter.report_incident(incident_key=f"circuit:{breaker_type.value}",category="circuit_breaker",severity="critical",title="Operational circuit breaker opened",context={"breaker":breaker_type.value,"reason_code":reason_code,"failure_count":result.failure_count,"threshold":result.threshold})
        return result

    def record_success(self, breaker_type: CircuitBreakerType) -> CircuitBreakerState:
        with self.store.locked_state() as state:
            b = self._ensure_breaker(state, breaker_type)
            b.last_success_at = datetime.now(timezone.utc)
            if b.open:
                # Explicitly no auto-resume. This only permits a later manual resume.
                b.recovery_observed = True
            else:
                b.failure_count = 0
            state.updated_at = datetime.now(timezone.utc)
            self.store.save_state(state)
            return b.model_copy(deep=True)

    def enforce_drawdown(self, *, current_equity: Decimal, peak_equity: Decimal, max_drawdown: Decimal) -> CircuitBreakerState:
        drawdown = max(peak_equity - current_equity, Decimal("0"))
        if drawdown >= max_drawdown:
            return self.record_failure(CircuitBreakerType.DRAWDOWN, reason_code="drawdown_limit_reached")
        return self.record_success(CircuitBreakerType.DRAWDOWN)

    def enforce_market_data_freshness(self, *, age_seconds: float, max_age_seconds: float) -> CircuitBreakerState:
        if age_seconds > max_age_seconds:
            return self.record_failure(CircuitBreakerType.STALE_MARKET_DATA, reason_code="market_data_stale")
        return self.record_success(CircuitBreakerType.STALE_MARKET_DATA)

    def enforce_clock_drift(self, *, drift_seconds: float, max_drift_seconds: float) -> CircuitBreakerState:
        if abs(drift_seconds) > max_drift_seconds:
            return self.record_failure(CircuitBreakerType.CLOCK_DRIFT, reason_code="clock_drift_exceeded")
        return self.record_success(CircuitBreakerType.CLOCK_DRIFT)

    def circuits(self) -> list[CircuitBreakerView]:
        state = self.store.load_state()
        # Include every configured breaker so operators can distinguish "closed" from "not initialized".
        views = []
        for breaker_type in CircuitBreakerType:
            b = state.circuits.get(breaker_type.value) or CircuitBreakerState(breaker=breaker_type, threshold=self.thresholds[breaker_type])
            views.append(CircuitBreakerView(**b.model_dump()))
        return views
