from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    CandidatePromotionEvaluation,
    ResearchCandidateStrategy,
    ResearchExperiment,
    ResearchHypothesis,
    ResearchObservation,
    TradeOutcome,
)

CANDIDATE_VERSION = "1.0.0"
GATE_VERSION = "1.0.0"
CANDIDATE_STATUSES = {
    "draft", "eligible", "blocked", "review_required", "approved_for_demo",
    "rejected", "archived",
}
D = Decimal

DEFAULT_GATE_CONFIG: dict[str, Any] = {
    "minimum_historical_sample": 5,
    "minimum_expectancy": "0.000001",
    "minimum_profit_factor": "1.00",
    "maximum_drawdown": "1000000",
    "minimum_stability": "0.35",
    "minimum_data_quality": "0.45",
    "maximum_execution_cost_ratio": "0.50",
    "execution_cost_warning_ratio": "0.25",
    "maximum_regime_concentration": "0.85",
    "maximum_parameter_specificity": 8,
    "performance_concentration_warning": "0.60",
}


class CandidateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_experiment_id: uuid.UUID
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    parent_candidate_id: uuid.UUID | None = None


class PromotionEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimum_historical_sample: int = Field(default=5, ge=1, le=1_000_000)
    minimum_expectancy: Decimal = Decimal("0.000001")
    minimum_profit_factor: Decimal = Field(default=Decimal("1.00"), ge=0)
    maximum_drawdown: Decimal = Field(default=Decimal("1000000"), ge=0)
    minimum_stability: Decimal = Field(default=Decimal("0.35"), ge=0, le=1)
    minimum_data_quality: Decimal = Field(default=Decimal("0.45"), ge=0, le=1)
    maximum_execution_cost_ratio: Decimal = Field(default=Decimal("0.50"), ge=0)
    execution_cost_warning_ratio: Decimal = Field(default=Decimal("0.25"), ge=0)
    maximum_regime_concentration: Decimal = Field(default=Decimal("0.85"), ge=0, le=1)
    maximum_parameter_specificity: int = Field(default=8, ge=1, le=1000)
    performance_concentration_warning: Decimal = Field(default=Decimal("0.60"), ge=0, le=1)


class CandidateRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    source_hypothesis_id: uuid.UUID
    source_experiment_id: uuid.UUID
    base_strategy_name: str | None
    base_strategy_version: str | None
    candidate_version: str
    symbol_scope: dict[str, Any]
    timeframe_scope: dict[str, Any]
    regime_scope: dict[str, Any]
    feature_conditions: dict[str, Any]
    entry_conditions: dict[str, Any]
    exit_conditions: dict[str, Any]
    risk_conditions: dict[str, Any]
    parameter_overrides: dict[str, Any]
    evidence_summary: dict[str, Any]
    evaluation_metrics: dict[str, Any]
    experiment_score: Decimal
    stability_score: Decimal
    data_quality_score: Decimal
    status: str
    configuration: dict[str, Any]
    configuration_hash: str
    parent_candidate_id: uuid.UUID | None
    research_observation_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class PromotionRead(BaseModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    gate_version: str
    overall_passed: bool
    review_required: bool
    sample_gate_passed: bool
    expectancy_gate_passed: bool
    profit_factor_gate_passed: bool
    drawdown_gate_passed: bool
    stability_gate_passed: bool
    data_quality_gate_passed: bool
    execution_cost_gate_passed: bool
    regime_robustness_gate_passed: bool
    gate_results: dict[str, Any]
    failure_reasons: list[Any]
    warnings: list[Any]
    configuration: dict[str, Any]
    configuration_hash: str
    evaluated_at: datetime
    created_at: datetime


def canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def dec(value: Any) -> Decimal:
    return D(str(value if value is not None else 0))


def _parameter_specificity(value: Any) -> int:
    if isinstance(value, dict):
        return sum(_parameter_specificity(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_parameter_specificity(v) for v in value)
    return 1 if value not in (None, "", {}) else 0


class ResearchCandidateService:
    """Research governance only. This class intentionally has no execution/runtime dependencies."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, request: CandidateCreateRequest) -> CandidateRead:
        experiment = self.db.get(ResearchExperiment, request.source_experiment_id)
        if experiment is None:
            raise LookupError("Research experiment not found")
        if experiment.status != "completed" or experiment.completed_at is None:
            raise ValueError("Candidate requires a completed research experiment")
        if not experiment.passed:
            raise ValueError("Candidate cannot be created from a failed research experiment")
        hypothesis = self.db.get(ResearchHypothesis, experiment.hypothesis_id)
        if hypothesis is None:
            raise LookupError("Source research hypothesis not found")
        if request.parent_candidate_id and self.db.get(ResearchCandidateStrategy, request.parent_candidate_id) is None:
            raise LookupError("Parent research candidate not found")

        parameter_overrides = experiment.comparison_metrics.get("candidate_parameters", {}) or {}
        historical_scope = {
            "train_start": experiment.train_start.isoformat(),
            "train_end": experiment.train_end.isoformat(),
            "validation_start": experiment.validation_start.isoformat() if experiment.validation_start else None,
            "validation_end": experiment.validation_end.isoformat() if experiment.validation_end else None,
            "evidence_outcome_ids": list(experiment.configuration.get("evidence_outcome_ids", [])),
            "scope_start": experiment.configuration.get("scope_start"),
            "scope_end": experiment.configuration.get("scope_end"),
        }
        config = {
            "candidate_version": CANDIDATE_VERSION,
            "parent_candidate_id": str(request.parent_candidate_id) if request.parent_candidate_id else None,
            "source_hypothesis": {
                "id": str(hypothesis.id),
                "version": hypothesis.hypothesis_version,
                "configuration_hash": hypothesis.configuration_hash,
            },
            "source_experiment": {
                "id": str(experiment.id),
                "version": experiment.experiment_version,
                "configuration_hash": experiment.configuration_hash,
            },
            "historical_scope": historical_scope,
            "symbol_scope": {"symbols": [hypothesis.symbol]} if hypothesis.symbol else {"symbols": []},
            "timeframe_scope": {"timeframes": [hypothesis.timeframe]} if hypothesis.timeframe else {"timeframes": []},
            "regime_scope": {"regimes": [hypothesis.regime]} if hypothesis.regime else {"regimes": []},
            "feature_conditions": hypothesis.feature_conditions or {},
            "entry_conditions": hypothesis.entry_conditions or {},
            "exit_conditions": hypothesis.exit_conditions or {},
            "risk_conditions": hypothesis.risk_conditions or {},
            "parameter_overrides": parameter_overrides,
            "hypothesis_configuration": hypothesis.configuration or {},
            "experiment_configuration": experiment.configuration or {},
        }
        config_hash = canonical_hash(config)
        existing = self.db.execute(
            select(ResearchCandidateStrategy).where(
                ResearchCandidateStrategy.source_experiment_id == experiment.id,
                ResearchCandidateStrategy.candidate_version == CANDIDATE_VERSION,
                ResearchCandidateStrategy.configuration_hash == config_hash,
            )
        ).scalar_one_or_none()
        if existing:
            return self._candidate_read(existing)

        row = ResearchCandidateStrategy(
            name=request.name or f"Candidate: {hypothesis.title}",
            description=request.description or f"Versioned research candidate derived from experiment {experiment.id}; requires explicit promotion review.",
            source_hypothesis_id=hypothesis.id,
            source_experiment_id=experiment.id,
            base_strategy_name=hypothesis.strategy_name,
            base_strategy_version=hypothesis.strategy_version,
            candidate_version=CANDIDATE_VERSION,
            symbol_scope=config["symbol_scope"], timeframe_scope=config["timeframe_scope"], regime_scope=config["regime_scope"],
            feature_conditions=hypothesis.feature_conditions or {}, entry_conditions=hypothesis.entry_conditions or {},
            exit_conditions=hypothesis.exit_conditions or {}, risk_conditions=hypothesis.risk_conditions or {},
            parameter_overrides=parameter_overrides,
            evidence_summary={
                "hypothesis_evidence": hypothesis.evidence_summary or {},
                "hypothesis_source_metrics": hypothesis.source_metrics or {},
                "historical_scope": historical_scope,
                "experiment_failure_reasons": experiment.failure_reasons or [],
            },
            evaluation_metrics={
                "result": experiment.result_metrics or {}, "baseline": experiment.baseline_metrics or {},
                "comparison": experiment.comparison_metrics or {}, "sample_size": experiment.sample_size,
                "baseline_sample_size": experiment.baseline_sample_size,
            },
            experiment_score=experiment.score, stability_score=experiment.stability_score,
            data_quality_score=experiment.data_quality_score, status="draft", configuration=config,
            configuration_hash=config_hash, parent_candidate_id=request.parent_candidate_id,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        obs = self._observe(row, "candidate_created", {
            "hypothesis_id": str(hypothesis.id), "experiment_id": str(experiment.id), "status": row.status,
            "scores": self._scores(row), "evidence_scope": historical_scope,
        })
        row.research_observation_id = obs.event_id
        self.db.commit(); self.db.refresh(row)
        return self._candidate_read(row)

    def evaluate(self, candidate_id: uuid.UUID, request: PromotionEvaluateRequest) -> PromotionRead:
        candidate = self._get_row(candidate_id)
        if candidate.status in {"approved_for_demo", "rejected", "archived"}:
            raise ValueError("Terminal candidate status cannot be re-evaluated")
        experiment = self.db.get(ResearchExperiment, candidate.source_experiment_id)
        if experiment is None or experiment.status != "completed" or not experiment.passed:
            raise ValueError("Candidate source experiment is not a completed passing experiment")

        config = request.model_dump(mode="json")
        config["gate_version"] = GATE_VERSION
        config["candidate_configuration_hash"] = candidate.configuration_hash
        config["source_experiment_configuration_hash"] = experiment.configuration_hash
        config_hash = canonical_hash(config)
        existing = self.db.execute(select(CandidatePromotionEvaluation).where(
            CandidatePromotionEvaluation.candidate_id == candidate.id,
            CandidatePromotionEvaluation.gate_version == GATE_VERSION,
            CandidatePromotionEvaluation.configuration_hash == config_hash,
        )).scalar_one_or_none()
        if existing:
            return self._promotion_read(existing)

        metrics = experiment.result_metrics or {}
        sample_size = int(experiment.sample_size or 0)
        expectancy = dec(metrics.get("expectancy"))
        profit_factor = dec(metrics.get("profit_factor"))
        drawdown = dec(metrics.get("max_drawdown"))
        fees = abs(dec(metrics.get("fees")))
        slippage = abs(dec(metrics.get("slippage")))
        gross_edge = abs(dec(metrics.get("gross_pnl")))
        execution_cost_ratio = (fees + slippage) / max(gross_edge, D("0.000001"))

        evidence_rows = self._evidence_outcomes(experiment)
        regime_counts: dict[str, int] = {}
        symbol_counts: dict[str, int] = {}
        for outcome in evidence_rows:
            regime_counts[str(outcome.regime_at_entry or "unknown")] = regime_counts.get(str(outcome.regime_at_entry or "unknown"), 0) + 1
            symbol_counts[outcome.symbol] = symbol_counts.get(outcome.symbol, 0) + 1
        dominant_regime_share = D(max(regime_counts.values(), default=0)) / D(len(evidence_rows) or 1)
        dominant_symbol_share = D(max(symbol_counts.values(), default=0)) / D(len(evidence_rows) or 1)

        sample_ok = sample_size >= request.minimum_historical_sample
        expectancy_ok = expectancy >= request.minimum_expectancy
        pf_ok = profit_factor >= request.minimum_profit_factor
        drawdown_ok = drawdown <= request.maximum_drawdown
        stability_ok = dec(experiment.stability_score) >= request.minimum_stability
        quality_ok = dec(experiment.data_quality_score) >= request.minimum_data_quality
        cost_ok = execution_cost_ratio <= request.maximum_execution_cost_ratio
        regime_ok = (not evidence_rows) or dominant_regime_share <= request.maximum_regime_concentration

        gate_results = {
            "sample_size": {"passed": sample_ok, "actual": sample_size, "minimum": request.minimum_historical_sample},
            "expectancy": {"passed": expectancy_ok, "actual": str(expectancy), "minimum": str(request.minimum_expectancy)},
            "profit_factor": {"passed": pf_ok, "actual": str(profit_factor), "minimum": str(request.minimum_profit_factor)},
            "drawdown": {"passed": drawdown_ok, "actual": str(drawdown), "maximum": str(request.maximum_drawdown)},
            "stability": {"passed": stability_ok, "actual": str(experiment.stability_score), "minimum": str(request.minimum_stability)},
            "data_quality": {"passed": quality_ok, "actual": str(experiment.data_quality_score), "minimum": str(request.minimum_data_quality)},
            "execution_cost": {"passed": cost_ok, "cost_ratio": str(execution_cost_ratio), "maximum": str(request.maximum_execution_cost_ratio)},
            "regime_robustness": {"passed": regime_ok, "dominant_share": str(dominant_regime_share), "maximum": str(request.maximum_regime_concentration), "counts": regime_counts},
        }
        failure_reasons = [
            {"code": name, **{k: v for k, v in result.items() if k != "passed"}}
            for name, result in gate_results.items() if not result["passed"]
        ]
        warnings = self._overfitting_warnings(candidate, experiment, evidence_rows, request, execution_cost_ratio, dominant_symbol_share, dominant_regime_share)
        overall = all(x["passed"] for x in gate_results.values())
        evaluated_at = datetime.now(timezone.utc)
        promotion = CandidatePromotionEvaluation(
            candidate_id=candidate.id, gate_version=GATE_VERSION, overall_passed=overall, review_required=True,
            sample_gate_passed=sample_ok, expectancy_gate_passed=expectancy_ok, profit_factor_gate_passed=pf_ok,
            drawdown_gate_passed=drawdown_ok, stability_gate_passed=stability_ok, data_quality_gate_passed=quality_ok,
            execution_cost_gate_passed=cost_ok, regime_robustness_gate_passed=regime_ok, gate_results=gate_results,
            failure_reasons=failure_reasons, warnings=warnings, configuration=config, configuration_hash=config_hash,
            evaluated_at=evaluated_at,
        )
        self.db.add(promotion)
        candidate.status = "eligible" if overall else "blocked"
        candidate.updated_at = evaluated_at
        self.db.commit(); self.db.refresh(promotion); self.db.refresh(candidate)
        self._observe(candidate, "candidate_evaluated", {
            "hypothesis_id": str(candidate.source_hypothesis_id), "experiment_id": str(candidate.source_experiment_id),
            "status": candidate.status, "gate_result": {"overall_passed": overall, **gate_results},
            "scores": self._scores(candidate), "warnings": warnings, "failure_reasons": failure_reasons,
        })
        return self._promotion_read(promotion)

    def request_review(self, candidate_id: uuid.UUID) -> CandidateRead:
        candidate = self._get_row(candidate_id)
        evaluation = self._latest_promotion(candidate.id)
        if candidate.status != "eligible" or evaluation is None or not evaluation.overall_passed:
            raise ValueError("Candidate must be eligible with passing promotion gates before review")
        candidate.status = "review_required"; candidate.updated_at = datetime.now(timezone.utc)
        self.db.commit(); self.db.refresh(candidate)
        self._observe(candidate, "candidate_review_requested", {
            "hypothesis_id": str(candidate.source_hypothesis_id), "experiment_id": str(candidate.source_experiment_id),
            "status": candidate.status, "gate_result": {"overall_passed": evaluation.overall_passed},
            "scores": self._scores(candidate), "warnings": evaluation.warnings, "failure_reasons": evaluation.failure_reasons,
        })
        return self._candidate_read(candidate)

    def approve_demo(self, candidate_id: uuid.UUID) -> CandidateRead:
        candidate = self._get_row(candidate_id)
        evaluation = self._latest_promotion(candidate.id)
        if candidate.status != "review_required":
            raise ValueError("Candidate must be in review_required state before demo approval")
        if evaluation is None or not evaluation.overall_passed or evaluation.failure_reasons:
            raise ValueError("Passing promotion evaluation with no blocking failure is required")
        candidate.status = "approved_for_demo"; candidate.updated_at = datetime.now(timezone.utc)
        self.db.commit(); self.db.refresh(candidate)
        self._observe(candidate, "candidate_approved_for_demo", {
            "hypothesis_id": str(candidate.source_hypothesis_id), "experiment_id": str(candidate.source_experiment_id),
            "status": candidate.status, "gate_result": {"overall_passed": True}, "scores": self._scores(candidate),
            "warnings": evaluation.warnings, "failure_reasons": [],
            "semantics": "research_governance_approval_only_no_bot_or_order_activation",
        })
        return self._candidate_read(candidate)

    def reject(self, candidate_id: uuid.UUID) -> CandidateRead:
        candidate = self._get_row(candidate_id)
        if candidate.status in {"approved_for_demo", "archived"}:
            raise ValueError("Candidate cannot be rejected from its current terminal state")
        candidate.status = "rejected"; candidate.updated_at = datetime.now(timezone.utc)
        self.db.commit(); self.db.refresh(candidate)
        evaluation = self._latest_promotion(candidate.id)
        self._observe(candidate, "candidate_rejected", {
            "hypothesis_id": str(candidate.source_hypothesis_id), "experiment_id": str(candidate.source_experiment_id),
            "status": candidate.status, "gate_result": {"overall_passed": evaluation.overall_passed} if evaluation else {},
            "scores": self._scores(candidate), "warnings": evaluation.warnings if evaluation else [],
            "failure_reasons": evaluation.failure_reasons if evaluation else [],
        })
        return self._candidate_read(candidate)

    def get(self, candidate_id: uuid.UUID) -> CandidateRead | None:
        row = self.db.get(ResearchCandidateStrategy, candidate_id)
        return self._candidate_read(row) if row else None

    def promotion(self, candidate_id: uuid.UUID) -> PromotionRead | None:
        if self.db.get(ResearchCandidateStrategy, candidate_id) is None:
            return None
        row = self._latest_promotion(candidate_id)
        return self._promotion_read(row) if row else None

    def list(self, *, status=None, base_strategy=None, source_hypothesis=None, source_experiment=None,
             symbol=None, timeframe=None, regime=None, minimum_experiment_score=None, minimum_stability=None,
             limit=100, offset=0) -> list[CandidateRead]:
        stmt = select(ResearchCandidateStrategy)
        if status: stmt = stmt.where(ResearchCandidateStrategy.status == status)
        if base_strategy: stmt = stmt.where(ResearchCandidateStrategy.base_strategy_name == base_strategy)
        if source_hypothesis: stmt = stmt.where(ResearchCandidateStrategy.source_hypothesis_id == source_hypothesis)
        if source_experiment: stmt = stmt.where(ResearchCandidateStrategy.source_experiment_id == source_experiment)
        if minimum_experiment_score is not None: stmt = stmt.where(ResearchCandidateStrategy.experiment_score >= minimum_experiment_score)
        if minimum_stability is not None: stmt = stmt.where(ResearchCandidateStrategy.stability_score >= minimum_stability)
        rows = self.db.execute(stmt.order_by(ResearchCandidateStrategy.created_at.desc(), ResearchCandidateStrategy.id.desc())).scalars().all()
        if symbol: rows = [r for r in rows if symbol.upper() in [str(x).upper() for x in r.symbol_scope.get("symbols", [])]]
        if timeframe: rows = [r for r in rows if timeframe in r.timeframe_scope.get("timeframes", [])]
        if regime: rows = [r for r in rows if regime in r.regime_scope.get("regimes", [])]
        return [self._candidate_read(r) for r in rows[offset:offset + limit]]

    def _evidence_outcomes(self, experiment: ResearchExperiment) -> list[TradeOutcome]:
        raw_ids = experiment.configuration.get("evidence_outcome_ids", []) or []
        ids = []
        for value in raw_ids:
            try: ids.append(uuid.UUID(str(value)))
            except (TypeError, ValueError): continue
        if not ids: return []
        rows = self.db.execute(select(TradeOutcome).where(TradeOutcome.id.in_(ids)).order_by(TradeOutcome.entry_time.asc(), TradeOutcome.id.asc())).scalars().all()
        return rows

    def _overfitting_warnings(self, candidate, experiment, rows, request, cost_ratio, symbol_share, regime_share):
        warnings = []
        if experiment.sample_size < request.minimum_historical_sample * 2:
            warnings.append({"code": "tiny_sample", "sample_size": experiment.sample_size})
        train = (experiment.result_metrics or {}).get("train", {})
        validation = (experiment.result_metrics or {}).get("validation", {})
        if validation and int(validation.get("trade_count", 0) or 0) > 0:
            te, ve = dec(train.get("expectancy")), dec(validation.get("expectancy"))
            if te > 0 and ve <= 0:
                warnings.append({"code": "train_validation_inconsistency", "train_expectancy": str(te), "validation_expectancy": str(ve)})
            elif te > 0 and ve < te * D("0.50"):
                warnings.append({"code": "validation_degradation", "train_expectancy": str(te), "validation_expectancy": str(ve)})
        specificity = _parameter_specificity({
            "feature": candidate.feature_conditions, "entry": candidate.entry_conditions, "exit": candidate.exit_conditions,
            "risk": candidate.risk_conditions, "parameters": candidate.parameter_overrides,
        })
        if specificity > request.maximum_parameter_specificity:
            warnings.append({"code": "excessive_parameter_specificity", "actual": specificity, "maximum": request.maximum_parameter_specificity})
        if rows and symbol_share >= D("0.95"):
            warnings.append({"code": "one_symbol_dependence", "dominant_share": str(symbol_share)})
        if candidate.regime_scope.get("regimes") or (rows and regime_share > request.maximum_regime_concentration):
            warnings.append({"code": "one_regime_dependence", "dominant_share": str(regime_share), "scope": candidate.regime_scope})
        positive = [max(dec(x.net_pnl), D("0")) for x in rows]
        positive_total = sum(positive, D("0"))
        if positive_total > 0:
            concentration = max(positive, default=D("0")) / positive_total
            if concentration > request.performance_concentration_warning:
                warnings.append({"code": "extreme_performance_concentration", "largest_win_share": str(concentration)})
        if dec(experiment.data_quality_score) < request.minimum_data_quality:
            warnings.append({"code": "poor_data_quality", "actual": str(experiment.data_quality_score)})
        if cost_ratio > request.execution_cost_warning_ratio:
            warnings.append({"code": "high_execution_cost_sensitivity", "cost_ratio": str(cost_ratio)})
        warnings.append({"code": "overfitting_not_proven_absent", "message": "Deterministic safeguards do not prove absence of overfitting."})
        return warnings

    def _latest_promotion(self, candidate_id):
        return self.db.execute(select(CandidatePromotionEvaluation).where(
            CandidatePromotionEvaluation.candidate_id == candidate_id
        ).order_by(CandidatePromotionEvaluation.evaluated_at.desc(), CandidatePromotionEvaluation.id.desc()).limit(1)).scalar_one_or_none()

    def _get_row(self, candidate_id):
        row = self.db.get(ResearchCandidateStrategy, candidate_id)
        if row is None: raise LookupError("Research candidate not found")
        return row

    def _observe(self, candidate, event_type, context):
        obs = ResearchObservation(event_type=event_type, source="research.candidates", symbol=(candidate.symbol_scope.get("symbols") or [None])[0],
            timeframe=(candidate.timeframe_scope.get("timeframes") or [None])[0], strategy_name=candidate.base_strategy_name,
            strategy_version=candidate.base_strategy_version, strategy_config_hash=candidate.configuration_hash,
            context={"candidate_id": str(candidate.id), **context})
        self.db.add(obs); self.db.commit(); self.db.refresh(obs)
        return obs

    @staticmethod
    def _scores(candidate):
        return {"experiment_score": str(candidate.experiment_score), "stability_score": str(candidate.stability_score), "data_quality_score": str(candidate.data_quality_score)}

    @staticmethod
    def _candidate_read(row):
        return CandidateRead.model_validate({k: getattr(row, k) for k in CandidateRead.model_fields})

    @staticmethod
    def _promotion_read(row):
        return PromotionRead.model_validate({k: getattr(row, k) for k in PromotionRead.model_fields})
