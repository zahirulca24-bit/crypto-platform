from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from models import (
    CandidatePromotionEvaluation,
    MarketFeatureSnapshot,
    MarketRegimeSnapshot,
    ResearchCandidateStrategy,
    ResearchExperiment,
    ResearchHypothesis,
    ResearchObservation,
    TradeOutcome,
)
from packages.research.features import FEATURE_VERSION
from packages.research.regimes import REGIME_VERSION
from packages.research.outcomes import OUTCOME_VERSION
from packages.research.hypotheses import HYPOTHESIS_VERSION
from packages.research.experiments import EXPERIMENT_VERSION
from packages.research.candidates import CANDIDATE_VERSION, GATE_VERSION

EXPECTED_MIGRATION_HEAD = "011_research_candidates"
ZERO = Decimal("0")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _performance_summary(rows: list[TradeOutcome]) -> dict[str, Any]:
    if not rows:
        return {
            "trade_count": 0, "win_rate": ZERO, "net_pnl": ZERO,
            "expectancy": ZERO, "profit_factor": None, "max_drawdown": ZERO,
        }
    pnls = [_decimal(row.net_pnl) for row in rows]
    wins = [v for v in pnls if v > 0]
    losses = [v for v in pnls if v < 0]
    gross_profit = sum(wins, ZERO)
    gross_loss = abs(sum(losses, ZERO))
    equity = ZERO
    peak = ZERO
    max_drawdown = ZERO
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "trade_count": len(rows),
        "win_rate": Decimal(len(wins)) / Decimal(len(rows)),
        "net_pnl": sum(pnls, ZERO),
        "expectancy": sum(pnls, ZERO) / Decimal(len(rows)),
        "profit_factor": (gross_profit / gross_loss) if gross_loss else None,
        "max_drawdown": max_drawdown,
    }


class ResearchIntegrationService:
    """Read-only Phase-3 integration/audit facade. It has no execution dependencies."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def overview(self, *, activity_limit: int = 20) -> dict[str, Any]:
        model_counts = {
            "observations": ResearchObservation,
            "feature_snapshots": MarketFeatureSnapshot,
            "regime_snapshots": MarketRegimeSnapshot,
            "trade_outcomes": TradeOutcome,
            "hypotheses": ResearchHypothesis,
            "experiments": ResearchExperiment,
            "candidates": ResearchCandidateStrategy,
        }
        counts = {key: self.db.scalar(select(func.count()).select_from(model)) or 0 for key, model in model_counts.items()}
        hypothesis_status = dict(self.db.execute(
            select(ResearchHypothesis.status, func.count()).group_by(ResearchHypothesis.status).order_by(ResearchHypothesis.status)
        ).all())
        candidate_status = {name: 0 for name in ("draft", "eligible", "blocked", "review_required", "approved_for_demo", "rejected", "archived")}
        candidate_status.update(dict(self.db.execute(
            select(ResearchCandidateStrategy.status, func.count()).group_by(ResearchCandidateStrategy.status).order_by(ResearchCandidateStrategy.status)
        ).all()))
        completed = self.db.scalar(select(func.count()).select_from(ResearchExperiment).where(ResearchExperiment.status == "completed")) or 0
        passed = self.db.scalar(select(func.count()).select_from(ResearchExperiment).where(ResearchExperiment.status == "completed", ResearchExperiment.passed.is_(True))) or 0
        failed = self.db.scalar(select(func.count()).select_from(ResearchExperiment).where(ResearchExperiment.status == "completed", ResearchExperiment.passed.is_(False))) or 0
        avg_score, avg_stability, avg_quality = self.db.execute(select(
            func.avg(ResearchExperiment.score), func.avg(ResearchExperiment.stability_score), func.avg(ResearchExperiment.data_quality_score)
        ).where(ResearchExperiment.status == "completed")).one()
        outcomes = self.db.execute(select(TradeOutcome).order_by(TradeOutcome.exit_time, TradeOutcome.id)).scalars().all()
        latest_regimes = self._latest_regimes(limit=20)
        activity = self.learning_journal(limit=activity_limit, offset=0)
        return {
            "counts": counts,
            "hypothesis_status_counts": hypothesis_status,
            "experiments": {
                "completed_count": completed, "passed_count": passed, "failed_count": failed,
                "average_score": _decimal(avg_score) if avg_score is not None else None,
                "average_stability": _decimal(avg_stability) if avg_stability is not None else None,
                "average_data_quality": _decimal(avg_quality) if avg_quality is not None else None,
            },
            "candidate_status_counts": candidate_status,
            "performance": _performance_summary(outcomes),
            "latest_regimes": latest_regimes,
            "recent_activity": activity,
        }

    def pipeline_status(self) -> dict[str, Any]:
        counts = {
            "observations": self._count(ResearchObservation),
            "features": self._count(MarketFeatureSnapshot),
            "regimes": self._count(MarketRegimeSnapshot),
            "outcomes": self._count(TradeOutcome),
            "hypotheses": self._count(ResearchHypothesis),
            "experiments": self._count(ResearchExperiment),
            "candidates": self._count(ResearchCandidateStrategy),
            "promotion_evaluations": self._count(CandidatePromotionEvaluation),
        }
        return {
            "counts": counts,
            "stages": {
                "observation_ready": counts["observations"] > 0,
                "feature_ready": counts["features"] > 0,
                "regime_ready": counts["regimes"] > 0,
                "outcome_ready": counts["outcomes"] > 0,
                "hypothesis_ready": counts["hypotheses"] > 0,
                "experiment_ready": counts["experiments"] > 0,
                "candidate_ready": counts["candidates"] > 0,
            },
            "research_only": True,
            "trading_activation": False,
        }

    def learning_journal(self, *, event_type=None, symbol=None, strategy=None, start=None, end=None, limit=100, offset=0) -> list[dict[str, Any]]:
        stmt = select(ResearchObservation)
        if event_type:
            stmt = stmt.where(ResearchObservation.event_type == event_type)
        if symbol:
            stmt = stmt.where(ResearchObservation.symbol == symbol.upper())
        if strategy:
            stmt = stmt.where(ResearchObservation.strategy_name == strategy)
        if start:
            stmt = stmt.where(ResearchObservation.observed_at >= start)
        if end:
            stmt = stmt.where(ResearchObservation.observed_at <= end)
        rows = self.db.execute(stmt.order_by(ResearchObservation.observed_at.desc(), ResearchObservation.event_id.desc()).offset(offset).limit(limit)).scalars().all()
        return [self._journal_row(row) for row in rows]

    def lineage(self, entity_type: str, entity_id: UUID) -> dict[str, Any]:
        entity_type = entity_type.lower().strip()
        handlers = {
            "observation": self._lineage_observation,
            "feature": self._lineage_feature,
            "regime": self._lineage_regime,
            "outcome": self._lineage_outcome,
            "hypothesis": self._lineage_hypothesis,
            "experiment": self._lineage_experiment,
            "candidate": self._lineage_candidate,
        }
        if entity_type not in handlers:
            raise ValueError("Unsupported research lineage entity type")
        result = handlers[entity_type](entity_id)
        if result is None:
            raise LookupError("Research lineage entity not found")
        return result

    def health(self) -> dict[str, Any]:
        self.db.execute(text("SELECT 1"))
        tables = [
            "research_observations", "market_feature_snapshots", "market_regime_snapshots",
            "trade_outcomes", "research_hypotheses", "research_experiments",
            "research_candidate_strategies", "candidate_promotion_evaluations",
        ]
        return {
            "status": "ok",
            "research_router_loaded": True,
            "database": "connected",
            "expected_models": tables,
            "versions": {
                "feature": FEATURE_VERSION, "regime": REGIME_VERSION, "outcome": OUTCOME_VERSION,
                "hypothesis": HYPOTHESIS_VERSION, "experiment": EXPERIMENT_VERSION,
                "candidate": CANDIDATE_VERSION, "promotion_gate": GATE_VERSION,
            },
            "expected_migration_head": EXPECTED_MIGRATION_HEAD,
            "postgresql_authoritative": True,
            "external_exchange_check_performed": False,
            "external_ai_required": False,
            "research_only": True,
        }

    def _count(self, model) -> int:
        return self.db.scalar(select(func.count()).select_from(model)) or 0

    def _latest_regimes(self, limit: int) -> list[dict[str, Any]]:
        rows = self.db.execute(select(MarketRegimeSnapshot).order_by(MarketRegimeSnapshot.candle_open_time.desc(), MarketRegimeSnapshot.id.desc()).limit(limit * 4)).scalars().all()
        seen: set[tuple[str, str, str]] = set()
        result = []
        for row in rows:
            key = (row.exchange, row.symbol, row.timeframe)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "id": row.id, "exchange": row.exchange, "symbol": row.symbol, "timeframe": row.timeframe,
                "candle_open_time": row.candle_open_time, "regime": row.regime,
                "confidence_score": row.confidence_score, "reason": row.reason,
                "transition_context": {"previous_regime": row.previous_regime, "current_regime": row.current_regime, "changed": row.changed, "transition_reason": row.transition_reason},
            })
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _journal_row(row: ResearchObservation) -> dict[str, Any]:
        return {
            "event_id": row.event_id, "event_type": row.event_type, "source": row.source,
            "observed_at": row.observed_at, "exchange": row.exchange, "symbol": row.symbol,
            "timeframe": row.timeframe, "bot_id": row.bot_id, "strategy_name": row.strategy_name,
            "strategy_version": row.strategy_version, "candle_open_time": row.candle_open_time,
            "selection_status": row.selection_status, "exit_reason": row.exit_reason,
            "realized_pnl": row.realized_pnl, "fees": row.fees, "slippage": row.slippage,
            "market_context": row.market_context, "trade_context": row.trade_context,
            "decision_context": row.decision_context, "context": row.context,
        }

    def _lineage_observation(self, entity_id):
        row = self.db.get(ResearchObservation, entity_id)
        if not row: return None
        downstream = {
            "features": [r.id for r in self.db.execute(select(MarketFeatureSnapshot).where(MarketFeatureSnapshot.observation_event_id == row.event_id)).scalars()],
            "regimes": [r.id for r in self.db.execute(select(MarketRegimeSnapshot).where(MarketRegimeSnapshot.observation_event_id == row.event_id)).scalars()],
            "outcomes": [r.id for r in self.db.execute(select(TradeOutcome).where(TradeOutcome.observation_event_id == row.event_id)).scalars()],
            "hypotheses": [r.id for r in self.db.execute(select(ResearchHypothesis).where(ResearchHypothesis.observation_event_id == row.event_id)).scalars()],
            "experiments": [r.id for r in self.db.execute(select(ResearchExperiment).where((ResearchExperiment.start_observation_event_id == row.event_id) | (ResearchExperiment.completion_observation_event_id == row.event_id))).scalars()],
            "candidates": [r.id for r in self.db.execute(select(ResearchCandidateStrategy).where(ResearchCandidateStrategy.research_observation_id == row.event_id)).scalars()],
        }
        return {"entity_type": "observation", "entity_id": row.event_id, "upstream": {}, "downstream": downstream}

    def _lineage_feature(self, entity_id):
        row = self.db.get(MarketFeatureSnapshot, entity_id)
        if not row: return None
        regimes = [r.id for r in self.db.execute(select(MarketRegimeSnapshot).where(MarketRegimeSnapshot.feature_snapshot_id == row.id)).scalars()]
        outcomes = [r.id for r in self.db.execute(select(TradeOutcome).where((TradeOutcome.entry_feature_snapshot_id == row.id) | (TradeOutcome.exit_feature_snapshot_id == row.id))).scalars()]
        return {"entity_type":"feature","entity_id":row.id,"upstream":{"candle_id":row.candle_id,"observation_id":row.observation_event_id},"downstream":{"regimes":regimes,"outcomes":outcomes}}

    def _lineage_regime(self, entity_id):
        row = self.db.get(MarketRegimeSnapshot, entity_id)
        if not row: return None
        outcomes = [r.id for r in self.db.execute(select(TradeOutcome).where((TradeOutcome.entry_regime_snapshot_id == row.id) | (TradeOutcome.exit_regime_snapshot_id == row.id))).scalars()]
        return {"entity_type":"regime","entity_id":row.id,"upstream":{"feature_snapshot_id":row.feature_snapshot_id,"observation_id":row.observation_event_id},"downstream":{"outcomes":outcomes}}

    def _lineage_outcome(self, entity_id):
        row = self.db.get(TradeOutcome, entity_id)
        if not row: return None
        needle = str(row.id)
        hypotheses = []
        for hypothesis in self.db.execute(select(ResearchHypothesis).order_by(ResearchHypothesis.created_at, ResearchHypothesis.id)).scalars():
            blob = str({"evidence_summary": hypothesis.evidence_summary, "source_metrics": hypothesis.source_metrics, "configuration": hypothesis.configuration})
            if needle in blob:
                hypotheses.append(hypothesis.id)
        experiments = []
        for experiment in self.db.execute(select(ResearchExperiment).order_by(ResearchExperiment.created_at, ResearchExperiment.id)).scalars():
            if needle in {str(value) for value in experiment.configuration.get("evidence_outcome_ids", [])}:
                experiments.append(experiment.id)
        return {"entity_type":"outcome","entity_id":row.id,"upstream":{"source_position_id":row.source_position_id,"observation_id":row.observation_event_id,"entry_feature_snapshot_id":row.entry_feature_snapshot_id,"exit_feature_snapshot_id":row.exit_feature_snapshot_id,"entry_regime_snapshot_id":row.entry_regime_snapshot_id,"exit_regime_snapshot_id":row.exit_regime_snapshot_id},"downstream":{"hypotheses":hypotheses,"experiments":experiments}}

    def _lineage_hypothesis(self, entity_id):
        row = self.db.get(ResearchHypothesis, entity_id)
        if not row: return None
        experiments = [r.id for r in self.db.execute(select(ResearchExperiment).where(ResearchExperiment.hypothesis_id == row.id).order_by(ResearchExperiment.created_at, ResearchExperiment.id)).scalars()]
        return {"entity_type":"hypothesis","entity_id":row.id,"upstream":{"parent_hypothesis_id":row.parent_hypothesis_id,"observation_id":row.observation_event_id,"evidence":row.evidence_summary,"source_metrics":row.source_metrics},"downstream":{"experiments":experiments}}

    def _lineage_experiment(self, entity_id):
        row = self.db.get(ResearchExperiment, entity_id)
        if not row: return None
        candidates = [r.id for r in self.db.execute(select(ResearchCandidateStrategy).where(ResearchCandidateStrategy.source_experiment_id == row.id).order_by(ResearchCandidateStrategy.created_at, ResearchCandidateStrategy.id)).scalars()]
        return {"entity_type":"experiment","entity_id":row.id,"upstream":{"hypothesis_id":row.hypothesis_id,"evidence_outcome_ids":row.configuration.get("evidence_outcome_ids",[]),"train_start":row.train_start,"train_end":row.train_end,"validation_start":row.validation_start,"validation_end":row.validation_end},"downstream":{"candidates":candidates}}

    def _lineage_candidate(self, entity_id):
        row = self.db.get(ResearchCandidateStrategy, entity_id)
        if not row: return None
        promotions = [r.id for r in self.db.execute(select(CandidatePromotionEvaluation).where(CandidatePromotionEvaluation.candidate_id == row.id).order_by(CandidatePromotionEvaluation.evaluated_at, CandidatePromotionEvaluation.id)).scalars()]
        return {"entity_type":"candidate","entity_id":row.id,"upstream":{"hypothesis_id":row.source_hypothesis_id,"experiment_id":row.source_experiment_id,"parent_candidate_id":row.parent_candidate_id,"historical_scope":row.configuration.get("historical_scope",{}),"evidence_summary":row.evidence_summary},"downstream":{"promotion_evaluations":promotions},"research_governance_only":True,"trading_activation":False}
