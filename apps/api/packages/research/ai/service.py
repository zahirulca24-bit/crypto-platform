from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models import (
    AIResearchProposal, CandidatePromotionEvaluation, MarketFeatureSnapshot, MarketRegimeSnapshot,
    ResearchCandidateStrategy, ResearchExperiment, ResearchHypothesis, ResearchObservation, TradeOutcome,
)
from packages.research.models import ObservationCreate
from packages.research.service import ResearchObservationService
from .gemini_provider import GeminiResearchProvider, AIProviderError, AIProviderNotConfigured
from .prompts import build_generation_prompt
from .provider import ResearchAIProvider
from .safety import sanitize_context, validate_condition_safety
from .schemas import (
    AIHealth, GenerateProposalsRequest, PROMPT_VERSION, PROPOSAL_STATUSES, PROPOSAL_VERSION,
    ProposalRead, StructuredProposal,
)

HYPOTHESIS_TYPE_MAP = {
    "hypothesis_candidate": "feature_condition",
    "strategy_filter_candidate": "strategy_filter",
    "feature_combination_candidate": "feature_condition",
    "parameter_candidate": "parameter_candidate",
    "regime_candidate": "regime_performance",
    "exit_improvement_candidate": "exit_behavior",
    "risk_research_candidate": "risk_behavior",
    "execution_quality_candidate": "execution_quality",
}

def canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

class ResearchContextBuilder:
    """Builds bounded, secret-filtered context solely from persisted research tables."""
    def __init__(self, db: Session): self.db = db
    def build(self, request: GenerateProposalsRequest) -> dict[str, Any]:
        limit = request.context_limit
        scope = {"strategy": request.strategy, "symbol": request.symbol.upper() if request.symbol else None,
                 "timeframe": request.timeframe, "regime": request.regime,
                 "start": request.start.isoformat() if request.start else None, "end": request.end.isoformat() if request.end else None,
                 "context_limit": limit}
        observations = self._rows(ResearchObservation, ResearchObservation.observed_at, request, limit)
        outcomes = self._rows(TradeOutcome, TradeOutcome.entry_time, request, limit)
        features = self._rows(MarketFeatureSnapshot, MarketFeatureSnapshot.candle_open_time, request, min(limit, 20))
        regimes = self._rows(MarketRegimeSnapshot, MarketRegimeSnapshot.candle_open_time, request, min(limit, 20))
        hypotheses = self._rows(ResearchHypothesis, ResearchHypothesis.created_at, request, min(limit, 20))
        experiments = self._rows(ResearchExperiment, ResearchExperiment.created_at, request, min(limit, 20))
        candidates = self._rows(ResearchCandidateStrategy, ResearchCandidateStrategy.created_at, request, min(limit, 20))
        promotions = self.db.execute(select(CandidatePromotionEvaluation).order_by(CandidatePromotionEvaluation.evaluated_at.desc(), CandidatePromotionEvaluation.id.desc()).limit(min(limit,20))).scalars().all()
        context = {
            "scope": scope,
            "counts": {
                "observations": self._count(ResearchObservation), "features": self._count(MarketFeatureSnapshot), "regimes": self._count(MarketRegimeSnapshot),
                "outcomes": self._count(TradeOutcome), "hypotheses": self._count(ResearchHypothesis), "experiments": self._count(ResearchExperiment),
                "candidates": self._count(ResearchCandidateStrategy), "promotion_evaluations": self._count(CandidatePromotionEvaluation),
            },
            "observations": [self._observation(x) for x in observations],
            "outcomes": [self._outcome(x) for x in outcomes],
            "features": [self._feature(x) for x in features],
            "regimes": [self._regime(x) for x in regimes],
            "hypotheses": [self._hypothesis(x) for x in hypotheses],
            "experiments": [self._experiment(x) for x in experiments],
            "candidates": [self._candidate(x) for x in candidates],
            "promotion_evaluations": [self._promotion(x) for x in promotions],
            "performance": self._performance(outcomes),
        }
        return sanitize_context(context)
    def _count(self, model): return int(self.db.scalar(select(func.count()).select_from(model)) or 0)
    def _rows(self, model, time_col, r, limit):
        s = select(model)
        if model is ResearchObservation:
            s = s.where(~ResearchObservation.event_type.like("ai_proposal_%"))
        if hasattr(model, "symbol") and r.symbol: s = s.where(model.symbol == r.symbol.upper())
        strategy_col = getattr(model, "strategy_name", None)
        if strategy_col is None: strategy_col = getattr(model, "base_strategy_name", None)
        if strategy_col is not None and r.strategy: s = s.where(strategy_col == r.strategy)
        if hasattr(model, "timeframe") and r.timeframe: s = s.where(model.timeframe == r.timeframe)
        regime_col = getattr(model, "regime", None)
        if regime_col is None: regime_col = getattr(model, "regime_at_entry", None)
        if regime_col is not None and r.regime: s = s.where(regime_col == r.regime)
        if r.start: s = s.where(time_col >= r.start)
        if r.end: s = s.where(time_col <= r.end)
        id_col = getattr(model, "id", None)
        if id_col is None: id_col = getattr(model, "event_id", None)
        return self.db.execute(s.order_by(time_col.desc(), id_col.desc()).limit(limit)).scalars().all()
    @staticmethod
    def _observation(x): return {"id":str(x.event_id),"event_type":x.event_type,"symbol":x.symbol,"timeframe":x.timeframe,"strategy":x.strategy_name,"observed_at":x.observed_at,"selection_status":x.selection_status,"realized_pnl":x.realized_pnl,"fees":x.fees,"slippage":x.slippage,"context":x.context}
    @staticmethod
    def _outcome(x): return {"id":str(x.id),"symbol":x.symbol,"timeframe":x.timeframe,"strategy":x.strategy_name,"entry_time":x.entry_time,"exit_time":x.exit_time,"net_pnl":x.net_pnl,"return_pct":x.return_pct,"r_multiple":x.r_multiple,"regime":x.regime_at_entry,"exit_reason":x.exit_reason,"fees":x.fees,"slippage":x.slippage,"entry_feature_snapshot_id":str(x.entry_feature_snapshot_id) if x.entry_feature_snapshot_id else None,"entry_regime_snapshot_id":str(x.entry_regime_snapshot_id) if x.entry_regime_snapshot_id else None}
    @staticmethod
    def _feature(x): return {"id":str(x.id),"symbol":x.symbol,"timeframe":x.timeframe,"candle_open_time":x.candle_open_time,"rsi":x.rsi,"macd":x.macd,"macd_signal":x.macd_signal,"volatility":x.volatility,"atr":x.atr,"moving_average_slope":x.moving_average_slope,"selection_score":x.selection_score,"selection_status":x.selection_status}
    @staticmethod
    def _regime(x): return {"id":str(x.id),"symbol":x.symbol,"timeframe":x.timeframe,"candle_open_time":x.candle_open_time,"regime":x.regime,"confidence_score":x.confidence_score,"reason":x.reason,"changed":x.changed,"previous_regime":x.previous_regime}
    @staticmethod
    def _hypothesis(x): return {"id":str(x.id),"type":x.hypothesis_type,"status":x.status,"title":x.title,"confidence_score":x.confidence_score,"priority_score":x.priority_score,"evidence_summary":x.evidence_summary}
    @staticmethod
    def _experiment(x): return {"id":str(x.id),"hypothesis_id":str(x.hypothesis_id),"type":x.experiment_type,"status":x.status,"sample_size":x.sample_size,"score":x.score,"stability_score":x.stability_score,"data_quality_score":x.data_quality_score,"passed":x.passed,"result_metrics":x.result_metrics,"comparison_metrics":x.comparison_metrics}
    @staticmethod
    def _candidate(x): return {"id":str(x.id),"hypothesis_id":str(x.source_hypothesis_id),"experiment_id":str(x.source_experiment_id),"status":x.status,"name":x.name,"experiment_score":x.experiment_score,"stability_score":x.stability_score,"data_quality_score":x.data_quality_score}
    @staticmethod
    def _promotion(x): return {"id":str(x.id),"candidate_id":str(x.candidate_id),"overall_passed":x.overall_passed,"failure_reasons":x.failure_reasons,"warnings":x.warnings,"evaluated_at":x.evaluated_at}
    @staticmethod
    def _performance(rows):
        n=len(rows); net=sum((Decimal(str(x.net_pnl)) for x in rows),Decimal("0")); wins=sum(1 for x in rows if x.net_pnl>0)
        return {"trade_count":n,"win_rate":str(Decimal(wins)/Decimal(n) if n else Decimal("0")),"net_pnl":str(net),"expectancy":str(net/Decimal(n) if n else Decimal("0"))}

class AIResearchService:
    """Research-only AI proposal service. Deliberately has no exchange/order/bot/risk/credential dependencies."""
    def __init__(self, db: Session, provider: ResearchAIProvider | None = None):
        self.db=db; self.provider=provider or GeminiResearchProvider(); self.context_builder=ResearchContextBuilder(db)
    def health(self) -> AIHealth:
        h=self.provider.health_check()
        return AIHealth(configured=bool(h.get("configured")),provider=str(h.get("provider", "google_gemini")),configured_model=str(h.get("model", self.provider.model_name)),proposal_version=PROPOSAL_VERSION,prompt_version=PROMPT_VERSION)
    def generate(self, request: GenerateProposalsRequest) -> list[ProposalRead]:
        if not self.provider.configured: raise AIProviderNotConfigured("AI research provider is not configured")
        context=self.context_builder.build(request); prompt=build_generation_prompt(context,request.max_proposals)
        batch, metadata=self.provider.generate_research_proposals(context=context,prompt=prompt,max_proposals=request.max_proposals)
        return [self._persist(p, request, context, metadata) for p in batch.proposals]
    def _persist(self, proposal: StructuredProposal, request, context, metadata):
        for payload in (proposal.feature_conditions,proposal.entry_conditions,proposal.exit_conditions,proposal.risk_conditions,proposal.parameter_suggestions): validate_condition_safety(payload)
        available = {
            "observations": {x["id"] for x in context["observations"]}, "outcomes": {x["id"] for x in context["outcomes"]},
            "hypotheses": {x["id"] for x in context["hypotheses"]}, "experiments": {x["id"] for x in context["experiments"]},
        }
        refs = {"observations":[str(x) for x in proposal.referenced_observation_ids],"outcomes":[str(x) for x in proposal.referenced_outcome_ids],"hypotheses":[str(x) for x in proposal.referenced_hypothesis_ids],"experiments":[str(x) for x in proposal.referenced_experiment_ids]}
        for key, values in refs.items():
            if not set(values).issubset(available[key]): raise ValueError(f"proposal references {key} outside the bounded data scope")
        data_scope={"request":context["scope"],"reference_ids":refs,"context_ids":{k:[str(x["id"]) for x in context[k]] for k in ("observations","outcomes","features","regimes","hypotheses","experiments","candidates","promotion_evaluations")},"context_counts":{k:len(context[k]) for k in ("observations","outcomes","features","regimes","hypotheses","experiments","candidates","promotion_evaluations")}}
        normalized=proposal.model_dump(mode="json")
        config={"proposal_version":PROPOSAL_VERSION,"prompt_version":PROMPT_VERSION,"provider":self.provider.provider_name,"model":self.provider.model_name,"temperature":getattr(self.provider,"temperature",None),"max_output_tokens":getattr(self.provider,"max_output_tokens",None),"data_scope":data_scope,"proposal":normalized}
        h=canonical_hash(config)
        existing=self.db.execute(select(AIResearchProposal).where(AIResearchProposal.proposal_version==PROPOSAL_VERSION,AIResearchProposal.prompt_version==PROMPT_VERSION,AIResearchProposal.provider==self.provider.provider_name,AIResearchProposal.model_name==self.provider.model_name,AIResearchProposal.configuration_hash==h)).scalar_one_or_none()
        if existing:return self._read(existing)
        row=AIResearchProposal(provider=self.provider.provider_name,model_name=self.provider.model_name,prompt_version=PROMPT_VERSION,
            **{k:v for k,v in normalized.items() if k not in {"model_confidence","research_priority","referenced_observation_ids","referenced_outcome_ids","referenced_hypothesis_ids","referenced_experiment_ids"}},
            referenced_observation_ids=refs["observations"],referenced_outcome_ids=refs["outcomes"],referenced_hypothesis_ids=refs["hypotheses"],referenced_experiment_ids=refs["experiments"],
            data_scope=data_scope,model_confidence=Decimal(str(proposal.model_confidence)) if proposal.model_confidence is not None else None,research_priority=Decimal(str(proposal.research_priority)) if proposal.research_priority is not None else None,
            raw_model_metadata=sanitize_context(metadata),status="generated",proposal_version=PROPOSAL_VERSION,configuration=config,configuration_hash=h)
        self.db.add(row)
        try:self.db.commit()
        except IntegrityError:
            self.db.rollback(); row=self.db.execute(select(AIResearchProposal).where(AIResearchProposal.configuration_hash==h)).scalar_one(); return self._read(row)
        self.db.refresh(row); self._observe(row,"ai_proposal_generated"); return self._read(row)
    def get(self, proposal_id):
        row=self.db.get(AIResearchProposal,proposal_id); return self._read(row) if row else None
    def list(self,*,provider=None,model=None,proposal_type=None,status=None,strategy=None,symbol=None,timeframe=None,regime=None,start=None,end=None,limit=100,offset=0):
        s=select(AIResearchProposal)
        for val,col in [(provider,AIResearchProposal.provider),(model,AIResearchProposal.model_name),(proposal_type,AIResearchProposal.proposal_type),(status,AIResearchProposal.status),(strategy,AIResearchProposal.strategy_name),(timeframe,AIResearchProposal.timeframe),(regime,AIResearchProposal.regime)]:
            if val is not None:s=s.where(col==val)
        if symbol:s=s.where(AIResearchProposal.symbol==symbol.upper())
        if start:s=s.where(AIResearchProposal.created_at>=start)
        if end:s=s.where(AIResearchProposal.created_at<=end)
        return [self._read(x) for x in self.db.execute(s.order_by(AIResearchProposal.created_at.desc(),AIResearchProposal.id.desc()).offset(offset).limit(limit)).scalars()]
    def set_status(self, proposal_id, status):
        if status not in PROPOSAL_STATUSES: raise ValueError("Unsupported AI proposal status")
        if status == "converted": raise ValueError("converted status is set only by explicit hypothesis conversion")
        row=self.db.get(AIResearchProposal,proposal_id)
        if not row: raise LookupError("AI research proposal not found")
        if row.status=="converted": raise ValueError("Converted proposal status is immutable")
        previous=row.status; row.status=status; row.updated_at=datetime.now(timezone.utc); self.db.commit(); self.db.refresh(row)
        self._observe(row,"ai_proposal_status_changed",{"previous_status":previous,"status":status}); return self._read(row)
    def create_hypothesis(self, proposal_id):
        row=self.db.get(AIResearchProposal,proposal_id)
        if not row: raise LookupError("AI research proposal not found")
        if row.status not in {"accepted_for_research","review_required","converted"}: raise ValueError("AI proposal must be accepted/reviewed before hypothesis conversion")
        if row.converted_hypothesis_id:
            existing=self.db.get(ResearchHypothesis,row.converted_hypothesis_id)
            if existing:return existing
        config={"source":"ai_research_proposal","ai_proposal_id":str(row.id),"ai_proposal_version":row.proposal_version,"ai_configuration_hash":row.configuration_hash,"provider":row.provider,"model":row.model_name,"prompt_version":row.prompt_version,"data_scope":row.data_scope}
        h=canonical_hash(config)
        existing=self.db.execute(select(ResearchHypothesis).where(ResearchHypothesis.hypothesis_type==HYPOTHESIS_TYPE_MAP[row.proposal_type],ResearchHypothesis.hypothesis_version=="1.0.0",ResearchHypothesis.configuration_hash==h)).scalar_one_or_none()
        if not existing:
            sample=len(row.referenced_outcome_ids)+len(row.referenced_observation_ids)
            evidence={"source":"ai_research_proposal","proposal_id":str(row.id),"observed_association":True,"causality_claimed":False,"requires_validation":True,"evidence_status":"ai_suggestion_unvalidated","supporting_evidence":row.supporting_evidence,"data_scope":row.data_scope}
            existing=ResearchHypothesis(hypothesis_type=HYPOTHESIS_TYPE_MAP[row.proposal_type],title=row.title,description=row.hypothesis_statement,status="proposed",strategy_name=row.strategy_name,strategy_version=None,symbol=row.symbol,timeframe=row.timeframe,regime=row.regime,
                feature_conditions=row.feature_conditions,entry_conditions=row.entry_conditions,exit_conditions=row.exit_conditions,risk_conditions=row.risk_conditions,evidence_summary=evidence,source_metrics={"ai_model_confidence":str(row.model_confidence) if row.model_confidence is not None else None,"ai_research_priority":str(row.research_priority) if row.research_priority is not None else None,"parameter_suggestions":row.parameter_suggestions},sample_size=sample,confidence_score=Decimal("0"),priority_score=row.research_priority or Decimal("0"),hypothesis_version="1.0.0",configuration=config,configuration_hash=h)
            self.db.add(existing); self.db.commit(); self.db.refresh(existing)
        row.converted_hypothesis_id=existing.id; row.status="converted"; row.updated_at=datetime.now(timezone.utc); self.db.commit(); self.db.refresh(row)
        self._observe(row,"ai_proposal_converted_to_hypothesis",{"hypothesis_id":str(existing.id)})
        return existing
    def _observe(self,row,event_type,extra=None):
        context={"proposal_id":str(row.id),"provider":row.provider,"model":row.model_name,"proposal_type":row.proposal_type,"status":row.status,"evidence_scope":row.data_scope}
        if extra:context.update(extra)
        obs=ResearchObservationService(self.db).record(ObservationCreate(event_type=event_type,source="ai_research",symbol=row.symbol,timeframe=row.timeframe,strategy_name=row.strategy_name,context=context))
        return obs
    @staticmethod
    def _read(row):
        data={name:getattr(row,name) for name in ProposalRead.model_fields}
        for name in ("model_confidence","research_priority"):
            if data[name] is not None:data[name]=float(data[name])
        return ProposalRead.model_validate(data)
