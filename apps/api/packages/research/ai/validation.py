from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from types import SimpleNamespace
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import (
    AIStrategyBlueprint,
    BlueprintSimulatedTrade,
    BlueprintValidationRun,
    MarketFeatureSnapshot,
    MarketRegimeSnapshot,
    OHLCVCandle,
)
from packages.research.models import ObservationCreate
from packages.research.service import ResearchObservationService

VALIDATION_VERSION = "1.0.0"
VALIDATION_TYPES = {
    "historical_backtest", "parameter_validation", "regime_validation",
    "walk_forward_validation", "execution_cost_validation", "robustness_validation",
}
VALIDATION_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}
EXECUTION_CONVENTION = "signal_close_next_candle_open"
DEFAULT_INTRABAR_POLICY = "stop_first"


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try: value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError): value = default
    if not math.isfinite(value): value = default
    return max(lo, min(hi, value))


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try: value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError): value = default
    return max(lo, min(hi, value))


def _d(value: Any) -> Decimal:
    if value is None: return Decimal("0")
    if isinstance(value, Decimal): return value
    return Decimal(str(value))


def _f(value: Any) -> float:
    if value is None: return 0.0
    return float(value)


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)


class BlueprintValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    validation_type: str = "historical_backtest"
    data_start: datetime | None = None
    data_end: datetime | None = None
    validation_fraction: float = Field(default=0.30, ge=0, le=0.8)
    symbol: str | None = None
    timeframe: str | None = None
    regime: str | None = None


class ValidationRead(BaseModel):
    id: UUID; blueprint_id: UUID; validation_type: str; status: str; validation_version: str
    symbol_scope: list[Any]; timeframe_scope: list[Any]; regime_scope: list[Any]
    data_start: datetime; data_end: datetime; train_start: datetime; train_end: datetime
    validation_start: datetime | None; validation_end: datetime | None
    configuration: dict[str, Any]; configuration_hash: str; parameter_set: dict[str, Any]; parameter_set_hash: str
    parameter_results: list[Any]; sample_size: int; signal_count: int; simulated_trade_count: int
    train_metrics: dict[str, Any]; validation_metrics: dict[str, Any]; combined_metrics: dict[str, Any]
    robustness_metrics: dict[str, Any]; execution_cost_metrics: dict[str, Any]
    score: float; stability_score: float; data_quality_score: float; overfit_risk_score: float
    passed: bool; failure_reasons: list[Any]; warnings: list[Any]
    started_at: datetime; completed_at: datetime | None; created_at: datetime


class SimulatedTradeRead(BaseModel):
    id: UUID; validation_run_id: UUID; blueprint_id: UUID; symbol: str; timeframe: str; side: str
    entry_time: datetime; exit_time: datetime; entry_price: Decimal; exit_price: Decimal; quantity: Decimal
    gross_pnl: Decimal; net_pnl: Decimal; return_pct: Decimal; simulated_fees: Decimal; simulated_slippage: Decimal
    mae: Decimal; mfe: Decimal; holding_time_seconds: int; exit_reason: str; entry_regime: str | None; exit_regime: str | None
    entry_feature_snapshot_id: UUID | None; entry_regime_snapshot_id: UUID | None; parameter_set_hash: str
    context: dict[str, Any]; created_at: datetime


class LogicInterpreter:
    """Safe JSON rule interpreter. It never evaluates source code or imports generated logic."""
    ALIASES = {"ema": "ema_fast", "sma": "sma_fast", "roc": "momentum", "price": "close"}
    OPS = {"<", "<=", ">", ">=", "==", "!=", "crosses_above", "crosses_below"}

    def value(self, indicator: str, candle: OHLCVCandle, feature: MarketFeatureSnapshot | None, regime: MarketRegimeSnapshot | None):
        key = self.ALIASES.get(indicator.lower(), indicator.lower())
        if key in {"open", "high", "low", "close", "volume"}: return getattr(candle, key)
        if key == "regime": return regime.regime if regime else None
        if not feature or not hasattr(feature, key): return None
        return getattr(feature, key)

    def _parameterized_target(self, rule: dict, parameters: dict[str, Any]):
        ind = str(rule.get("indicator", "")).lower()
        for name, value in parameters.items():
            lname = name.lower()
            if ind in lname and ("threshold" in lname or "level" in lname or lname == ind): return value
        return rule.get("value")

    def rule(self, rule: dict, current: tuple, previous: tuple | None, parameters: dict[str, Any]) -> bool:
        indicator = str(rule.get("indicator", "")).lower(); op = rule.get("operator")
        if op not in self.OPS: raise ValueError(f"unsupported rule operator: {op}")
        candle, feature, regime = current; left = self.value(indicator, candle, feature, regime)
        reference = rule.get("reference")
        if reference is not None: right = self.value(str(reference).lower(), candle, feature, regime)
        else: right = self._parameterized_target(rule, parameters)
        if left is None or right is None: return False
        if op in {"crosses_above", "crosses_below"}:
            if previous is None: return False
            pc, pf, pr = previous; pleft = self.value(indicator, pc, pf, pr)
            pright = self.value(str(reference).lower(), pc, pf, pr) if reference is not None else right
            if pleft is None or pright is None: return False
            return (pleft <= pright and left > right) if op == "crosses_above" else (pleft >= pright and left < right)
        try:
            if op == "<": return left < right
            if op == "<=": return left <= right
            if op == ">": return left > right
            if op == ">=": return left >= right
            if op == "==": return left == right
            return left != right
        except TypeError:
            return str(left) == str(right) if op == "==" else str(left) != str(right) if op == "!=" else False

    def group(self, logic: dict, current: tuple, previous: tuple | None, parameters: dict[str, Any]) -> bool:
        all_rules = logic.get("all", []) if isinstance(logic, dict) else []
        any_rules = logic.get("any", []) if isinstance(logic, dict) else []
        all_ok = all(self.rule(r, current, previous, parameters) for r in all_rules) if all_rules else True
        any_ok = any(self.rule(r, current, previous, parameters) for r in any_rules) if any_rules else True
        return all_ok and any_ok


class BlueprintValidationService:
    """Research-only deterministic historical validation; no trading/exchange/runtime dependencies."""
    def __init__(self, db: Session): self.db = db; self.interpreter = LogicInterpreter()

    def validate(self, blueprint_id: UUID, req: BlueprintValidationRequest) -> ValidationRead:
        if req.validation_type not in VALIDATION_TYPES: raise ValueError("unsupported validation type")
        bp = self.db.get(AIStrategyBlueprint, blueprint_id)
        if not bp: raise LookupError("AI strategy blueprint not found")
        if bp.status != "accepted_for_validation": raise ValueError("blueprint must be accepted_for_validation")
        if bp.blocking_reasons: raise ValueError("blueprint contains blocking reasons")
        config = self._configuration(bp, req)
        records = self._records(bp, req)
        if len(records) < 2: raise ValueError("insufficient closed candle/feature history for validation")
        config["data_scope"] = {
            "candle_ids": [str(x[0].id) for x in records],
            "feature_ids": [str(x[1].id) for x in records if x[1]],
            "regime_ids": [str(x[2].id) for x in records if x[2]],
        }
        config["data_start"] = records[0][0].open_time.isoformat(); config["data_end"] = records[-1][0].open_time.isoformat()
        config_hash = canonical_hash(config)
        existing = self.db.execute(select(BlueprintValidationRun).where(
            BlueprintValidationRun.blueprint_id == bp.id,
            BlueprintValidationRun.validation_version == VALIDATION_VERSION,
            BlueprintValidationRun.validation_type == req.validation_type,
            BlueprintValidationRun.configuration_hash == config_hash,
        )).scalar_one_or_none()
        if existing: return self._read(existing)
        try:
            return self._execute(bp, req, records, config, config_hash)
        except ValueError as exc:
            return self._persist_failed(bp, req, records, config, config_hash, str(exc))
        except Exception as exc:
            # Sanitized failure state; never expose provider/DB secrets or affect execution services.
            try:
                return self._persist_failed(bp, req, records, config, config_hash, f"validation_error:{type(exc).__name__}")
            except Exception:
                self.db.rollback()
                raise RuntimeError(f"blueprint validation failed: {type(exc).__name__}") from exc

    def validate_variant(self, variant, req: BlueprintValidationRequest) -> ValidationRead:
        """Reuse the P4-04 engine for an immutable research variant.

        The persisted validation remains in the blueprint validation table, while
        the exact source_variant_id and variant hash are part of the reproducible
        configuration. No production strategy object is created or mutated.
        """
        bp = self.db.get(AIStrategyBlueprint, variant.source_blueprint_id)
        if not bp:
            raise LookupError("source AI strategy blueprint not found")
        fixed_space = {k: {"values": [v]} for k, v in sorted((variant.parameter_values or {}).items())}
        subject = SimpleNamespace(
            id=bp.id, status="accepted_for_validation", blocking_reasons=[],
            blueprint_version=bp.blueprint_version, configuration_hash=variant.configuration_hash,
            symbol_scope=variant.symbol_scope, timeframe_scope=variant.timeframe_scope, regime_scope=variant.regime_scope,
            parameter_space=fixed_space, entry_logic=variant.entry_logic, exit_logic=variant.exit_logic,
            protection_logic=variant.protection_logic, risk_constraints=variant.risk_constraints,
            indicator_requirements=variant.indicator_requirements, base_strategy_name=bp.base_strategy_name,
        )
        config = self._configuration(subject, req)
        config["source_variant_id"] = str(variant.id)
        config["variant_configuration_hash"] = variant.configuration_hash
        records = self._records(subject, req)
        if len(records) < 2:
            raise ValueError("insufficient closed candle/feature history for validation")
        config["data_scope"] = {
            "candle_ids": [str(x[0].id) for x in records],
            "feature_ids": [str(x[1].id) for x in records if x[1]],
            "regime_ids": [str(x[2].id) for x in records if x[2]],
        }
        config["data_start"] = records[0][0].open_time.isoformat()
        config["data_end"] = records[-1][0].open_time.isoformat()
        config_hash = canonical_hash(config)
        existing = self.db.execute(select(BlueprintValidationRun).where(
            BlueprintValidationRun.blueprint_id == bp.id,
            BlueprintValidationRun.validation_version == VALIDATION_VERSION,
            BlueprintValidationRun.validation_type == req.validation_type,
            BlueprintValidationRun.configuration_hash == config_hash,
        )).scalar_one_or_none()
        if existing:
            return self._read(existing)
        try:
            return self._execute(subject, req, records, config, config_hash)
        except ValueError as exc:
            return self._persist_failed(subject, req, records, config, config_hash, str(exc))

    def _configuration(self, bp, req):
        intrabar_policy = os.getenv("AI_BACKTEST_INTRABAR_CONFLICT_POLICY", DEFAULT_INTRABAR_POLICY).strip().lower()
        # P4-04 only supports the conservative ordering. Unknown values must never
        # silently select the profitable path.
        if intrabar_policy != "stop_first":
            intrabar_policy = DEFAULT_INTRABAR_POLICY
        return {
            "validation_version": VALIDATION_VERSION,
            "blueprint_version": bp.blueprint_version,
            "blueprint_configuration_hash": bp.configuration_hash,
            "validation_type": req.validation_type,
            "requested_data_start": req.data_start.isoformat() if req.data_start else None,
            "requested_data_end": req.data_end.isoformat() if req.data_end else None,
            "validation_fraction": req.validation_fraction,
            "execution_convention": EXECUTION_CONVENTION,
            "intrabar_conflict_policy": intrabar_policy,
            "fee_bps": _env_float("AI_BACKTEST_FEE_BPS", 10.0, 0, 1000),
            "slippage_bps": _env_float("AI_BACKTEST_SLIPPAGE_BPS", 5.0, 0, 1000),
            "sizing_model": "fixed_notional",
            "fixed_notional": _env_float("AI_BACKTEST_FIXED_NOTIONAL", 1000.0, 1, 1000000),
            "gates": self._gates(),
            "max_parameter_combinations": _env_int("AI_BLUEPRINT_MAX_PARAMETER_COMBINATIONS", 500, 1, 100000),
            "symbol": req.symbol,
            "timeframe": req.timeframe,
            "regime": req.regime,
        }

    def _gates(self):
        return {
            "minimum_trades": _env_int("AI_VALIDATION_MIN_TRADES", 10, 1, 100000),
            "minimum_expectancy": _env_float("AI_VALIDATION_MIN_EXPECTANCY", 0.0, -1000000, 1000000),
            "minimum_profit_factor": _env_float("AI_VALIDATION_MIN_PROFIT_FACTOR", 1.05, 0, 100),
            "maximum_drawdown": _env_float("AI_VALIDATION_MAX_DRAWDOWN", 20.0, 0, 1000000),
            "minimum_stability": _env_float("AI_VALIDATION_MIN_STABILITY", 0.50, 0, 1),
            "minimum_data_quality": _env_float("AI_VALIDATION_MIN_DATA_QUALITY", 0.60, 0, 1),
            "maximum_overfit_risk": _env_float("AI_VALIDATION_MAX_OVERFIT_RISK", 0.65, 0, 1),
            "maximum_execution_cost_drag": _env_float("AI_VALIDATION_MAX_EXECUTION_COST_DRAG", 0.60, 0, 10),
        }

    def _records(self, bp, req):
        symbol = req.symbol or (bp.symbol_scope[0] if bp.symbol_scope else None)
        timeframe = req.timeframe or (bp.timeframe_scope[0] if bp.timeframe_scope else None)
        if not symbol or not timeframe: raise ValueError("blueprint validation requires symbol and timeframe scope")
        q = select(OHLCVCandle).where(OHLCVCandle.symbol == symbol, OHLCVCandle.timeframe == timeframe, OHLCVCandle.is_closed.is_(True))
        if req.data_start: q = q.where(OHLCVCandle.open_time >= req.data_start)
        if req.data_end: q = q.where(OHLCVCandle.open_time <= req.data_end)
        candles = self.db.execute(q.order_by(OHLCVCandle.open_time.asc(), OHLCVCandle.id.asc())).scalars().all()
        features = self.db.execute(select(MarketFeatureSnapshot).where(MarketFeatureSnapshot.symbol == symbol, MarketFeatureSnapshot.timeframe == timeframe).order_by(MarketFeatureSnapshot.candle_open_time.asc(), MarketFeatureSnapshot.created_at.asc())).scalars().all()
        regimes = self.db.execute(select(MarketRegimeSnapshot).where(MarketRegimeSnapshot.symbol == symbol, MarketRegimeSnapshot.timeframe == timeframe).order_by(MarketRegimeSnapshot.candle_open_time.asc(), MarketRegimeSnapshot.created_at.asc())).scalars().all()
        f_by_candle = {f.candle_id: f for f in features}; r_by_feature = {r.feature_snapshot_id: r for r in regimes}
        result=[]
        for c in candles:
            f=f_by_candle.get(c.id); f = f if (f and f.candle_open_time <= c.open_time) else None
            r=r_by_feature.get(f.id) if f else None; r = r if (r and r.candle_open_time <= c.open_time) else None
            if req.regime and (not r or r.regime != req.regime): continue
            result.append((c,f,r))
        return result

    def _parameter_sets(self, bp, max_count: int):
        if not bp.parameter_space: return [{}]
        names=[]; choices=[]
        for name, spec in sorted(bp.parameter_space.items()):
            names.append(name)
            if spec.get("values") is not None: vals=list(spec["values"])
            else:
                lo, hi, step = spec.get("min"), spec.get("max"), spec.get("step")
                if lo is None or hi is None or step is None or float(step) <= 0: raise ValueError("invalid parameter range")
                vals=[]; cur=Decimal(str(lo)); dhi=Decimal(str(hi)); ds=Decimal(str(step)); guard=0
                while cur <= dhi and guard <= max_count: vals.append(float(cur) if cur % 1 else int(cur)); cur += ds; guard += 1
            choices.append(vals)
        total=math.prod(len(x) for x in choices)
        if total > max_count: raise ValueError("parameter search space exceeds configured maximum")
        return [dict(zip(names, vals)) for vals in itertools.product(*choices)]

    @staticmethod
    def _split(records, fraction):
        n=len(records)
        if fraction <= 0 or n < 4: return records, []
        cut=max(2, min(n-1, int(math.floor(n*(1-fraction)))))
        return records[:cut], records[cut:]

    def _execute(self, bp, req, records, config, config_hash):
        train_records, val_records = self._split(records, req.validation_fraction)
        max_params=config["max_parameter_combinations"]; psets=self._parameter_sets(bp,max_params)
        ranked=[]
        for p in psets:
            trades,signals=self._simulate(bp,train_records,p,config)
            m=self.metrics(trades); ranked.append({"parameter_set":p,"parameter_set_hash":canonical_hash(p),"training_score":self._training_score(m),"train_metrics":m,"signal_count":signals})
        ranked.sort(key=lambda x:(x["training_score"],x["train_metrics"].get("trade_count",0),x["parameter_set_hash"]),reverse=True)
        selected=ranked[0] if ranked else {"parameter_set":{},"parameter_set_hash":canonical_hash({}),"training_score":0,"train_metrics":self.metrics([]),"signal_count":0}
        params=selected["parameter_set"]; p_hash=selected["parameter_set_hash"]
        full_trades, full_signals = self._simulate(bp, records, params, config)
        train_trades=[t for t in full_trades if t["entry_time"] <= train_records[-1][0].open_time and t["exit_time"] <= train_records[-1][0].open_time]
        val_trades=[t for t in full_trades if val_records and t["entry_time"] >= val_records[0][0].open_time]
        train_m=self.metrics(train_trades); val_m=self.metrics(val_trades); combined=self.metrics(full_trades)
        quality=self._data_quality(bp, records)
        sensitivity=self._parameter_sensitivity(ranked)
        walk=self._walk_forward(bp, records, psets, config) if req.validation_type=="walk_forward_validation" else []
        stability=self._stability(train_m,val_m,combined,sensitivity,walk)
        overfit=self._overfit(train_m,val_m,len(psets),len(bp.parameter_space),stability,sensitivity,combined)
        robustness={"parameter_sensitivity":sensitivity,"walk_forward_segments":walk,"train_validation_consistency":round(1-abs(_f(train_m["expectancy"])-_f(val_m["expectancy"]))/max(1,abs(_f(train_m["expectancy"])),abs(_f(val_m["expectancy"]))),6) if val_trades else 0.0,"regime_performance":combined.get("regime_performance",{})}
        gross=abs(_f(combined["gross_pnl"])); costs=_f(combined["fees_total"])+_f(combined["slippage_total"]); cost_drag=costs/gross if gross>0 else (1.0 if costs>0 else 0.0)
        execution={"fee_bps":config["fee_bps"],"slippage_bps":config["slippage_bps"],"fees_total":combined["fees_total"],"slippage_total":combined["slippage_total"],"cost_drag_ratio":round(cost_drag,6)}
        score=self._validation_score(val_m if val_records else combined,stability,quality,overfit,cost_drag)
        failures=self._gate_failures(val_m if val_records else combined,stability,quality,overfit,cost_drag,config["gates"])
        warnings=[]
        if not val_records:warnings.append("validation_window_unavailable")
        if sensitivity<0.5:warnings.append("parameter_sensitivity_high")
        if overfit>0.65:warnings.append("elevated_overfit_risk")
        row=BlueprintValidationRun(blueprint_id=bp.id,validation_type=req.validation_type,status="running",validation_version=VALIDATION_VERSION,symbol_scope=[records[0][0].symbol],timeframe_scope=[records[0][0].timeframe],regime_scope=bp.regime_scope,data_start=records[0][0].open_time,data_end=records[-1][0].open_time,train_start=train_records[0][0].open_time,train_end=train_records[-1][0].open_time,validation_start=val_records[0][0].open_time if val_records else None,validation_end=val_records[-1][0].open_time if val_records else None,configuration=config,configuration_hash=config_hash,parameter_set=params,parameter_set_hash=p_hash,parameter_results=ranked,sample_size=len(records),signal_count=full_signals,simulated_trade_count=len(full_trades),train_metrics=train_m,validation_metrics=val_m,combined_metrics=combined,robustness_metrics=robustness,execution_cost_metrics=execution,score=Decimal(str(score)),stability_score=Decimal(str(stability)),data_quality_score=Decimal(str(quality)),overfit_risk_score=Decimal(str(overfit)),passed=not failures,failure_reasons=failures,warnings=warnings,started_at=datetime.now(timezone.utc))
        self.db.add(row); self.db.flush()
        for t in full_trades:
            self.db.add(BlueprintSimulatedTrade(validation_run_id=row.id,blueprint_id=bp.id,symbol=t["symbol"],timeframe=t["timeframe"],side=t["side"],entry_time=t["entry_time"],exit_time=t["exit_time"],entry_price=t["entry_price"],exit_price=t["exit_price"],quantity=t["quantity"],gross_pnl=t["gross_pnl"],net_pnl=t["net_pnl"],return_pct=t["return_pct"],simulated_fees=t["simulated_fees"],simulated_slippage=t["simulated_slippage"],mae=t["mae"],mfe=t["mfe"],holding_time_seconds=t["holding_time_seconds"],exit_reason=t["exit_reason"],entry_regime=t["entry_regime"],exit_regime=t["exit_regime"],entry_feature_snapshot_id=t["entry_feature_snapshot_id"],entry_regime_snapshot_id=t["entry_regime_snapshot_id"],parameter_set_hash=p_hash,context=t["context"]))
        row.status="completed"; row.completed_at=datetime.now(timezone.utc)
        try:self.db.commit()
        except IntegrityError:
            self.db.rollback(); existing=self.db.execute(select(BlueprintValidationRun).where(BlueprintValidationRun.blueprint_id==bp.id,BlueprintValidationRun.validation_version==VALIDATION_VERSION,BlueprintValidationRun.validation_type==req.validation_type,BlueprintValidationRun.configuration_hash==config_hash)).scalar_one(); return self._read(existing)
        self.db.refresh(row); self._observe(row,bp,"ai_blueprint_validation_started"); self._observe(row,bp,"ai_blueprint_validation_completed"); return self._read(row)


    def _persist_failed(self, bp, req, records, config, config_hash, reason):
        existing=self.db.execute(select(BlueprintValidationRun).where(BlueprintValidationRun.blueprint_id==bp.id,BlueprintValidationRun.validation_version==VALIDATION_VERSION,BlueprintValidationRun.validation_type==req.validation_type,BlueprintValidationRun.configuration_hash==config_hash)).scalar_one_or_none()
        if existing:return self._read(existing)
        train_records,val_records=self._split(records,req.validation_fraction)
        safe_reason=str(reason)[:240]
        row=BlueprintValidationRun(blueprint_id=bp.id,validation_type=req.validation_type,status="failed",validation_version=VALIDATION_VERSION,symbol_scope=[records[0][0].symbol],timeframe_scope=[records[0][0].timeframe],regime_scope=bp.regime_scope,data_start=records[0][0].open_time,data_end=records[-1][0].open_time,train_start=train_records[0][0].open_time,train_end=train_records[-1][0].open_time,validation_start=val_records[0][0].open_time if val_records else None,validation_end=val_records[-1][0].open_time if val_records else None,configuration=config,configuration_hash=config_hash,parameter_set={},parameter_set_hash=canonical_hash({}),parameter_results=[],sample_size=len(records),signal_count=0,simulated_trade_count=0,train_metrics=self.metrics([]),validation_metrics=self.metrics([]),combined_metrics=self.metrics([]),robustness_metrics={},execution_cost_metrics={"fee_bps":config["fee_bps"],"slippage_bps":config["slippage_bps"]},score=Decimal("0"),stability_score=Decimal("0"),data_quality_score=Decimal("0"),overfit_risk_score=Decimal("1"),passed=False,failure_reasons=[safe_reason],warnings=[],started_at=datetime.now(timezone.utc),completed_at=datetime.now(timezone.utc))
        self.db.add(row)
        try:self.db.commit()
        except IntegrityError:
            self.db.rollback(); row=self.db.execute(select(BlueprintValidationRun).where(BlueprintValidationRun.blueprint_id==bp.id,BlueprintValidationRun.validation_version==VALIDATION_VERSION,BlueprintValidationRun.validation_type==req.validation_type,BlueprintValidationRun.configuration_hash==config_hash)).scalar_one(); return self._read(row)
        self.db.refresh(row); self._observe(row,bp,"ai_blueprint_validation_failed"); return self._read(row)

    def _simulate(self,bp,records,params,config):
        trades=[]; signals=0; i=0
        tp_pct=_d(bp.exit_logic.get("take_profit_pct",0))/Decimal("100"); sl_pct=_d(bp.exit_logic.get("stop_loss_pct",0))/Decimal("100")
        max_hold=int(bp.exit_logic.get("max_holding_candles",50) or 50); side="long"
        while i < len(records)-1:
            cur=records[i]; prev=records[i-1] if i>0 else None
            if not self.interpreter.group(bp.entry_logic,cur,prev,params): i+=1; continue
            signals+=1; entry_idx=i+1; ec,ef,er=records[entry_idx]
            # signal on i, execution on next candle open; slippage is adverse.
            slip_rate=_d(config["slippage_bps"])/Decimal("10000"); fee_rate=_d(config["fee_bps"])/Decimal("10000")
            raw_entry=_d(ec.open); entry=raw_entry*(Decimal("1")+slip_rate); notional=_d(config["fixed_notional"]); qty=notional/entry if entry>0 else Decimal("0")
            tp=entry*(Decimal("1")+tp_pct) if tp_pct>0 else None; sl=entry*(Decimal("1")-sl_pct) if sl_pct>0 else None
            exit_idx=None; exit_price=None; reason="end_of_data"
            path=[]
            last=min(len(records)-1,entry_idx+max_hold)
            for j in range(entry_idx,last+1):
                c,f,r=records[j]; path.append(records[j])
                hit_tp=bool(tp and _d(c.high)>=tp); hit_sl=bool(sl and _d(c.low)<=sl)
                if hit_tp and hit_sl:
                    exit_idx=j; exit_price=sl if config["intrabar_conflict_policy"]=="stop_first" else tp; reason="stop_loss" if config["intrabar_conflict_policy"]=="stop_first" else "take_profit"; break
                if hit_sl: exit_idx=j; exit_price=sl; reason="stop_loss"; break
                if hit_tp: exit_idx=j; exit_price=tp; reason="take_profit"; break
                exit_logic=bp.exit_logic.get("conditions")
                if isinstance(exit_logic,dict) and j < len(records)-1 and self.interpreter.group(exit_logic,records[j],records[j-1] if j>0 else None,params):
                    exit_idx=j+1; exit_price=_d(records[j+1][0].open); reason="strategy_exit"; break
            if exit_idx is None:
                # A time-based exit is confirmed after the held candle closes and,
                # when possible, executes at the next available candle open. Only
                # terminal end-of-data uses the final close because no next candle
                # exists to execute against.
                if last < len(records)-1:
                    exit_idx=last+1; exit_price=_d(records[exit_idx][0].open); reason="time_exit"
                else:
                    exit_idx=last; exit_price=_d(records[last][0].close); reason="end_of_data"
            xc,xf,xr=records[exit_idx]; exit_price=_d(exit_price)*(Decimal("1")-slip_rate)
            gross=(exit_price-entry)*qty; fees=(entry*qty+exit_price*qty)*fee_rate; slippage=(abs(entry-raw_entry)+abs(_d(exit_price)-_d(exit_price)/(Decimal("1")-slip_rate) if slip_rate<1 else Decimal("0")))*qty; net=gross-fees
            lows=[_d(x[0].low) for x in path] or [entry]; highs=[_d(x[0].high) for x in path] or [entry]
            mae=min(Decimal("0"),(min(lows)-entry)*qty); mfe=max(Decimal("0"),(max(highs)-entry)*qty)
            trades.append({"symbol":ec.symbol,"timeframe":ec.timeframe,"side":side,"entry_time":ec.open_time,"exit_time":xc.open_time,"entry_price":_q(entry),"exit_price":_q(exit_price),"quantity":_q(qty),"gross_pnl":_q(gross),"net_pnl":_q(net),"return_pct":_q((net/notional)*Decimal("100") if notional else Decimal("0")),"simulated_fees":_q(fees),"simulated_slippage":_q(slippage),"mae":_q(mae),"mfe":_q(mfe),"holding_time_seconds":max(0,int((xc.open_time-ec.open_time).total_seconds())),"exit_reason":reason,"entry_regime":er.regime if er else None,"exit_regime":xr.regime if xr else None,"entry_feature_snapshot_id":ef.id if ef else None,"entry_regime_snapshot_id":er.id if er else None,"context":{"signal_candle_id":str(cur[0].id),"signal_time":cur[0].open_time.isoformat(),"entry_candle_id":str(ec.id),"exit_candle_id":str(xc.id),"execution_convention":EXECUTION_CONVENTION,"intrabar_conflict_policy":config["intrabar_conflict_policy"],"matched_entry_conditions":bp.entry_logic,"parameter_set":params}})
            i=max(i+1,exit_idx+1)
        return trades,signals

    @staticmethod
    def metrics(trades):
        n=len(trades); pnl=[_f(t["net_pnl"]) for t in trades]; wins=[x for x in pnl if x>0]; losses=[x for x in pnl if x<0]
        gross_profit=sum(wins); gross_loss=abs(sum(losses)); pf=(gross_profit/gross_loss if gross_loss>0 else (999.0 if gross_profit>0 else 0.0)); expectancy=sum(pnl)/n if n else 0.0
        equity=0.0; peak=0.0; maxdd=0.0
        for x in pnl: equity+=x; peak=max(peak,equity); maxdd=max(maxdd,peak-equity)
        returns=[_f(t["return_pct"]) for t in trades]
        regimes={}
        for t in trades:
            k=t.get("entry_regime") or "unknown"; regimes.setdefault(k,[]).append(_f(t["net_pnl"]))
        return {"trade_count":n,"wins":len(wins),"losses":len(losses),"win_rate":round(len(wins)/n if n else 0,6),"gross_pnl":round(sum(_f(t["gross_pnl"]) for t in trades),6),"net_pnl":round(sum(pnl),6),"average_win":round(sum(wins)/len(wins) if wins else 0,6),"average_loss":round(sum(losses)/len(losses) if losses else 0,6),"expectancy":round(expectancy,6),"profit_factor":round(min(pf,999.0),6),"max_drawdown":round(maxdd,6),"average_mae":round(sum(_f(t["mae"]) for t in trades)/n if n else 0,6),"average_mfe":round(sum(_f(t["mfe"]) for t in trades)/n if n else 0,6),"average_holding_time":round(sum(t["holding_time_seconds"] for t in trades)/n if n else 0,6),"fees_total":round(sum(_f(t["simulated_fees"]) for t in trades),6),"slippage_total":round(sum(_f(t["simulated_slippage"]) for t in trades),6),"return_distribution":{"min":round(min(returns),6) if returns else 0,"max":round(max(returns),6) if returns else 0,"mean":round(sum(returns)/len(returns),6) if returns else 0},"regime_performance":{k:{"trade_count":len(v),"net_pnl":round(sum(v),6),"expectancy":round(sum(v)/len(v),6)} for k,v in sorted(regimes.items())}}

    @staticmethod
    def _training_score(m):
        n=m["trade_count"]; exp=math.tanh(max(-10,min(10,_f(m["expectancy"])/10))); pf=min(2,_f(m["profit_factor"]))/2; dd=1/(1+max(0,_f(m["max_drawdown"]))/100); sample=min(1,n/20)
        return round(max(0,min(1,0.35*((exp+1)/2)+0.25*pf+0.2*dd+0.2*sample)),6)

    def _data_quality(self,bp,records):
        required={str(x).lower() for x in bp.indicator_requirements}; total=max(1,len(records)); feature_ok=0; regime_ok=0
        for c,f,r in records:
            vals=True
            for ind in required:
                if ind in {"open","high","low","close","volume","price"}: continue
                if ind=="regime": vals=vals and r is not None
                else:
                    key=self.interpreter.ALIASES.get(ind,ind); vals=vals and f is not None and hasattr(f,key) and getattr(f,key) is not None
            feature_ok+=int(vals); regime_ok+=int(r is not None)
        completeness=feature_ok/total; regime_ratio=regime_ok/total if bp.regime_scope or "regime" in required else 1.0; sample=min(1,total/50)
        return round(max(0,min(1,0.5*completeness+0.25*regime_ratio+0.25*sample)),6)

    @staticmethod
    def _parameter_sensitivity(ranked):
        if len(ranked)<=1:return 1.0
        scores=[x["training_score"] for x in ranked]; best=max(scores); near=sorted(scores,reverse=True)[:min(5,len(scores))]
        spread=max(near)-min(near) if near else 1
        return round(max(0,min(1,1-spread/max(0.1,best))),6)

    def _walk_forward(self,bp,records,psets,config):
        if len(records)<8:return []
        seg=[]; window=max(2,len(records)//4)
        cursor=window
        while cursor+window<=len(records):
            train=records[max(0,cursor-window):cursor]; val=records[cursor:cursor+window]
            ranked=[]
            for p in psets:
                t,_=self._simulate(bp,train,p,config); m=self.metrics(t); ranked.append((self._training_score(m),canonical_hash(p),p))
            ranked.sort(reverse=True,key=lambda x:(x[0],x[1])); p=ranked[0][2]
            vt,_=self._simulate(bp,val,p,config); seg.append({"train_start":train[0][0].open_time.isoformat(),"train_end":train[-1][0].open_time.isoformat(),"validation_start":val[0][0].open_time.isoformat(),"validation_end":val[-1][0].open_time.isoformat(),"parameter_set":p,"validation_metrics":self.metrics(vt)})
            cursor+=window
        return seg

    @staticmethod
    def _stability(train,val,combined,sensitivity,walk):
        if val.get("trade_count",0):
            te=_f(train["expectancy"]); ve=_f(val["expectancy"]); consistency=max(0,1-abs(te-ve)/max(1,abs(te),abs(ve))); direction=1 if te*ve>=0 else 0
        else: consistency=0.35; direction=0.5
        regime_values=[x["expectancy"] for x in combined.get("regime_performance",{}).values()]; regime=1.0 if len(regime_values)<=1 else max(0,1-(max(regime_values)-min(regime_values))/max(1,abs(max(regime_values)),abs(min(regime_values))))
        wf=1.0
        if walk:
            exps=[_f(x["validation_metrics"]["expectancy"]) for x in walk]; wf=sum(1 for x in exps if x>=0)/len(exps)
        return round(max(0,min(1,0.35*consistency+0.15*direction+0.2*regime+0.2*sensitivity+0.1*wf)),6)

    @staticmethod
    def _overfit(train,val,param_sets,param_count,stability,sensitivity,combined):
        risk=0.15+min(0.25,param_count*0.03)+min(0.2,math.log10(max(1,param_sets))*0.08)+0.2*(1-stability)+0.15*(1-sensitivity)
        if val.get("trade_count",0) and _f(train["expectancy"])>0 and _f(val["expectancy"])<=0:risk+=0.2
        if combined.get("trade_count",0)<10:risk+=0.15
        return round(max(0,min(1,risk)),6)

    @staticmethod
    def _validation_score(m,stability,quality,overfit,cost_drag):
        exp=(math.tanh(_f(m["expectancy"])/10)+1)/2; pf=min(2,_f(m["profit_factor"]))/2; dd=1/(1+_f(m["max_drawdown"])/100); sample=min(1,m.get("trade_count",0)/20); cost=max(0,1-min(1,cost_drag))
        return round(max(0,min(1,0.2*exp+0.15*pf+0.1*dd+0.1*sample+0.2*stability+0.15*quality+0.05*(1-overfit)+0.05*cost)),6)

    @staticmethod
    def _gate_failures(m,stability,quality,overfit,cost_drag,g):
        failures=[]
        if m.get("trade_count",0)<g["minimum_trades"]:failures.append("minimum_simulated_trades_not_met")
        if _f(m.get("expectancy"))<=g["minimum_expectancy"]:failures.append("minimum_validation_expectancy_not_met")
        if _f(m.get("profit_factor"))<g["minimum_profit_factor"]:failures.append("minimum_profit_factor_not_met")
        if _f(m.get("max_drawdown"))>g["maximum_drawdown"]:failures.append("maximum_drawdown_exceeded")
        if stability<g["minimum_stability"]:failures.append("minimum_stability_not_met")
        if quality<g["minimum_data_quality"]:failures.append("minimum_data_quality_not_met")
        if overfit>g["maximum_overfit_risk"]:failures.append("maximum_overfit_risk_exceeded")
        if cost_drag>g["maximum_execution_cost_drag"]:failures.append("maximum_execution_cost_drag_exceeded")
        return failures

    def get(self, validation_id: UUID):
        row=self.db.get(BlueprintValidationRun,validation_id); return self._read(row) if row else None

    def list(self, **f):
        q=select(BlueprintValidationRun)
        for key,col in (("blueprint",BlueprintValidationRun.blueprint_id),("validation_type",BlueprintValidationRun.validation_type),("status",BlueprintValidationRun.status),("passed",BlueprintValidationRun.passed)):
            if f.get(key) is not None:q=q.where(col==f[key])
        if f.get("minimum_score") is not None:q=q.where(BlueprintValidationRun.score>=Decimal(str(f["minimum_score"])))
        if f.get("maximum_overfit_risk") is not None:q=q.where(BlueprintValidationRun.overfit_risk_score<=Decimal(str(f["maximum_overfit_risk"])))
        if f.get("start") is not None:q=q.where(BlueprintValidationRun.created_at>=f["start"])
        if f.get("end") is not None:q=q.where(BlueprintValidationRun.created_at<=f["end"])
        rows=self.db.execute(q.order_by(BlueprintValidationRun.created_at.desc(),BlueprintValidationRun.id.desc())).scalars().all()
        def scoped(r):return (not f.get("symbol") or f["symbol"].upper() in [str(x).upper() for x in r.symbol_scope]) and (not f.get("timeframe") or f["timeframe"] in r.timeframe_scope) and (not f.get("regime") or f["regime"] in r.regime_scope)
        rows=[r for r in rows if scoped(r)]; off=f.get("offset",0); lim=f.get("limit",100); return [self._read(x) for x in rows[off:off+lim]]

    def trades(self, validation_id):
        if not self.db.get(BlueprintValidationRun,validation_id):raise LookupError("Blueprint validation not found")
        rows=self.db.execute(select(BlueprintSimulatedTrade).where(BlueprintSimulatedTrade.validation_run_id==validation_id).order_by(BlueprintSimulatedTrade.entry_time.asc(),BlueprintSimulatedTrade.id.asc())).scalars().all(); return [self._trade_read(x) for x in rows]

    def blueprint_validations(self, blueprint_id):
        if not self.db.get(AIStrategyBlueprint,blueprint_id):raise LookupError("AI strategy blueprint not found")
        return self.list(blueprint=blueprint_id)

    def parameters(self, validation_id):
        row=self.db.get(BlueprintValidationRun,validation_id)
        if not row:raise LookupError("Blueprint validation not found")
        return {"validation_id":str(row.id),"selected_parameter_set":row.parameter_set,"selected_parameter_set_hash":row.parameter_set_hash,"parameter_results":row.parameter_results}

    def robustness(self, validation_id):
        row=self.db.get(BlueprintValidationRun,validation_id)
        if not row:raise LookupError("Blueprint validation not found")
        return {"validation_id":str(row.id),"stability_score":float(row.stability_score),"data_quality_score":float(row.data_quality_score),"overfit_risk_score":float(row.overfit_risk_score),"robustness_metrics":row.robustness_metrics,"execution_cost_metrics":row.execution_cost_metrics}

    def _observe(self,row,bp,event):
        try:
            return ResearchObservationService(self.db).record(ObservationCreate(event_type=event,source="ai_blueprint_validation",symbol=row.symbol_scope[0] if row.symbol_scope else None,timeframe=row.timeframe_scope[0] if row.timeframe_scope else None,strategy_name=bp.base_strategy_name,context={"validation_id":str(row.id),"blueprint_id":str(bp.id),"validation_type":row.validation_type,"sample_size":row.sample_size,"simulated_trade_count":row.simulated_trade_count,"score":str(row.score),"stability_score":str(row.stability_score),"data_quality_score":str(row.data_quality_score),"overfit_risk_score":str(row.overfit_risk_score),"passed":row.passed,"failure_reasons":row.failure_reasons}))
        except Exception:
            self.db.rollback(); return None

    @staticmethod
    def _read(row):
        d={k:getattr(row,k) for k in ValidationRead.model_fields};
        for k in ("score","stability_score","data_quality_score","overfit_risk_score"):d[k]=float(d[k])
        return ValidationRead.model_validate(d)
    @staticmethod
    def _trade_read(row):return SimulatedTradeRead.model_validate({k:getattr(row,k) for k in SimulatedTradeRead.model_fields})
