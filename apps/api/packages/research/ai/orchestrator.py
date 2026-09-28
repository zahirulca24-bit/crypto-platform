from __future__ import annotations
import os, re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models import AIProposalReview, AIResearchProposal, AIResearchRun, ResearchCandidateStrategy, ResearchExperiment, ResearchHypothesis, ResearchObservation
from packages.research.models import ObservationCreate
from packages.research.service import observe_best_effort
from .gemini_provider import AIProviderError, GeminiResearchProvider
from .prompts import build_generation_prompt
from .provider import ResearchAIProvider
from .schemas import AIProposalReviewRead, AIResearchRunRead, GenerateProposalsRequest, ORCHESTRATOR_VERSION, PROMPT_VERSION, REVIEW_VERSION, ResearchRunRequest
from .service import AIResearchService, ResearchContextBuilder, canonical_hash

CRITICAL_PATTERNS = {
    "risk_engine_bypass": r"bypass\s+(?:the\s+)?risk|disable\s+risk|remove\s+risk\s+cap",
    "credential_access": r"api\s*key|credential|password|private\s*key|secret",
    "order_execution": r"submit\s+(?:an?\s+)?order|place\s+(?:an?\s+)?order|execute\s+trade",
    "demo_activation": r"auto(?:matically)?[-\s]+(?:enable|activate).{0,20}demo",
    "live_trading": r"enable.{0,20}live|activate.{0,20}live|approved_for_live",
    "withdrawal": r"withdraw(?:al)?",
    "dynamic_code": r"eval\s*\(|exec\s*\(|generated\s+code|run\s+(?:python|shell|script)",
    "production_config_mutation": r"modify.{0,30}production.{0,20}(?:strategy|config)",
    "stop_loss_removal": r"remove.{0,20}(?:stop[-\s]?loss|\bsl\b).{0,40}win\s*rate",
}

def _env_float(name: str, default: float) -> float:
    try: return min(1.0,max(0.0,float(os.getenv(name,str(default)))))
    except ValueError: return default

def _env_int(name: str, default: int, lo=1, hi=20) -> int:
    try: return min(hi,max(lo,int(os.getenv(name,str(default)))))
    except ValueError: return default

class AIResearchOrchestrator:
    """Coordinates research AI only; deliberately has no trading/runtime/risk/credential dependencies."""
    def __init__(self, db: Session, provider: ResearchAIProvider | None=None):
        self.db=db; self.provider=provider or GeminiResearchProvider(); self.ai=AIResearchService(db,self.provider); self.builder=ResearchContextBuilder(db)
    def thresholds(self):
        return {"min_evidence_score":_env_float("AI_REVIEW_MIN_EVIDENCE_SCORE",0.35),"min_testability_score":_env_float("AI_REVIEW_MIN_TESTABILITY_SCORE",0.45),"min_data_quality_score":_env_float("AI_REVIEW_MIN_DATA_QUALITY_SCORE",0.35),"min_overall_score":_env_float("AI_REVIEW_MIN_OVERALL_SCORE",0.50),"max_proposals_per_run":_env_int("AI_RESEARCH_MAX_PROPOSALS_PER_RUN",5,1,20)}
    def run(self, req: ResearchRunRequest) -> AIResearchRunRead:
        th=self.thresholds(); maxp=min(req.max_proposals or th["max_proposals_per_run"], th["max_proposals_per_run"])
        gen=GenerateProposalsRequest(strategy=req.strategy,symbol=req.symbol,timeframe=req.timeframe,regime=req.regime,start=req.start,end=req.end,max_proposals=maxp,context_limit=max(5,min(100,req.recent_outcome_count)))
        context=self.builder.build(gen); evidence=self._evidence_scope(context); config={"orchestrator_version":ORCHESTRATOR_VERSION,"prompt_version":PROMPT_VERSION,"run_type":req.run_type,"scope":context["scope"],"recent_outcome_count":req.recent_outcome_count,"minimum_sample_size":req.minimum_sample_size,"thresholds":th,"max_proposals":maxp,"evidence_scope":evidence}
        now=datetime.now(timezone.utc); row=AIResearchRun(run_type=req.run_type,status="running",provider=self.provider.provider_name,model_name=self.provider.model_name,prompt_version=PROMPT_VERSION,orchestrator_version=ORCHESTRATOR_VERSION,symbol_scope=[req.symbol] if req.symbol else [],timeframe_scope=[req.timeframe] if req.timeframe else [],regime_scope=[req.regime] if req.regime else [],strategy_scope=[req.strategy] if req.strategy else [],data_start=req.start,data_end=req.end,context_summary={"counts":context["counts"],"bounded_counts":{k:len(context[k]) for k in ("observations","outcomes","features","regimes","hypotheses","experiments","candidates","promotion_evaluations")}},evidence_scope=evidence,proposals_requested=maxp,proposals_generated=0,proposals_accepted=0,proposals_suppressed=0,proposals_rejected=0,run_metrics={},warnings=[],failure_reason=None,configuration=config,configuration_hash=canonical_hash(config),started_at=now)
        self.db.add(row); self.db.commit(); self.db.refresh(row); self._observe("ai_research_run_started",row)
        try:
            if not self.provider.configured: raise AIProviderError("AI research provider is not configured")
            batch, metadata=self.provider.generate_research_proposals(context=context,prompt=build_generation_prompt(context,maxp),max_proposals=maxp)
            proposals=[]
            for p in batch.proposals[:maxp]: proposals.append(self.ai._persist(p,gen,context,metadata))
            reviews=[self.review(p.id,row.id,req.minimum_sample_size,th) for p in proposals]
            row.proposals_generated=len(proposals); row.proposals_accepted=sum(1 for x in reviews if x.accepted_for_review); row.proposals_suppressed=sum(1 for x in reviews if x.suppressed); row.proposals_rejected=sum(1 for x in reviews if (not x.accepted_for_review and not x.suppressed)); row.run_metrics={"ranked_proposal_ids":[str(x.proposal_id) for x in sorted(reviews,key=lambda x:(x.overall_score,str(x.proposal_id)),reverse=True)],"provider_calls":1,"model_confidence_authoritative":False}; row.status="completed"; row.completed_at=datetime.now(timezone.utc); self.db.commit(); self._observe("ai_research_run_completed",row); return self._read_run(row)
        except Exception as exc:
            self.db.rollback(); row=self.db.get(AIResearchRun,row.id); row.status="failed"; row.failure_reason=self._sanitize_error(exc); row.completed_at=datetime.now(timezone.utc); row.run_metrics={"provider_calls":1 if self.provider.configured else 0}; self.db.commit(); self._observe("ai_research_run_failed",row); return self._read_run(row)
    def review(self, proposal_id, run_id, minimum_sample_size=10, thresholds=None):
        p=self.db.get(AIResearchProposal,proposal_id); run=self.db.get(AIResearchRun,run_id)
        if not p or not run: raise LookupError("proposal or research run not found")
        th=thresholds or self.thresholds(); cfg={"review_version":REVIEW_VERSION,"thresholds":th,"minimum_sample_size":minimum_sample_size,"run_evidence_scope":run.evidence_scope}; h=canonical_hash(cfg)
        existing=self.db.execute(select(AIProposalReview).where(AIProposalReview.proposal_id==p.id,AIProposalReview.research_run_id==run.id,AIProposalReview.review_version==REVIEW_VERSION,AIProposalReview.configuration_hash==h)).scalar_one_or_none()
        if existing:return self._read_review(existing)
        invalid_scope=self._invalid_scope(p,run); evidence,em=self._evidence_score(p,run,minimum_sample_size); novelty,nm=self._novelty_score(p); testability,tm=self._testability_score(p); quality,qm=self._data_quality_score(p,run,minimum_sample_size); safety,sm=self._safety_score(p)
        reasons=[]; warnings=[]
        if invalid_scope: reasons.append("invalid_evidence_scope")
        if safety<=0: reasons.extend(sm["violations"])
        if evidence < th["min_evidence_score"]: reasons.append("insufficient_evidence")
        if testability < th["min_testability_score"]: reasons.append("insufficient_testability")
        if quality < th["min_data_quality_score"]: reasons.append("insufficient_data_quality")
        if novelty <= 0.15: reasons.append("material_duplicate")
        econ=self._economic_relevance(p,run); overall=round(0.25*evidence+0.18*novelty+0.20*testability+0.17*quality+0.15*safety+0.05*econ,6)
        if overall < th["min_overall_score"]: reasons.append("overall_score_below_threshold")
        suppressed=bool(invalid_scope or safety<=0 or evidence<0.15 or testability<0.20 or novelty<=0.05); accepted=(not suppressed and not reasons)
        if 0 < novelty < 0.4: warnings.append("low_novelty")
        row=AIProposalReview(proposal_id=p.id,research_run_id=run.id,review_version=REVIEW_VERSION,evidence_score=Decimal(str(evidence)),novelty_score=Decimal(str(novelty)),testability_score=Decimal(str(testability)),data_quality_score=Decimal(str(quality)),safety_score=Decimal(str(safety)),overall_score=Decimal(str(overall)),accepted_for_review=accepted,suppressed=suppressed,rejection_reasons=sorted(set(reasons)),warnings=warnings,review_metrics={"evidence":em,"novelty":nm,"testability":tm,"data_quality":qm,"safety":sm,"economic_relevance":econ,"model_confidence":str(p.model_confidence) if p.model_confidence is not None else None,"model_confidence_authoritative":False},configuration=cfg,configuration_hash=h)
        self.db.add(row)
        try:self.db.commit()
        except IntegrityError:self.db.rollback(); row=self.db.execute(select(AIProposalReview).where(AIProposalReview.proposal_id==p.id,AIProposalReview.research_run_id==run.id,AIProposalReview.review_version==REVIEW_VERSION,AIProposalReview.configuration_hash==h)).scalar_one()
        self.db.refresh(row); self._observe("ai_proposal_suppressed" if row.suppressed else "ai_proposal_reviewed",run,proposal=p,review=row); return self._read_review(row)
    def request_review(self, proposal_id):
        p=self.db.get(AIResearchProposal,proposal_id)
        if not p: raise LookupError("AI proposal not found")
        review=self.db.execute(select(AIProposalReview).where(AIProposalReview.proposal_id==p.id).order_by(AIProposalReview.created_at.desc(),AIProposalReview.id.desc())).scalar_one_or_none()
        if not review: raise ValueError("proposal has not been deterministically reviewed")
        if review.suppressed or not review.accepted_for_review: raise ValueError("proposal did not pass deterministic review thresholds")
        p.status="review_required"; self.db.commit(); self.db.refresh(p); run=self.db.get(AIResearchRun,review.research_run_id); self._observe("ai_proposal_review_requested",run,proposal=p,review=review); return self.ai._read(p)
    def get_review(self,proposal_id):
        row=self.db.execute(select(AIProposalReview).where(AIProposalReview.proposal_id==proposal_id).order_by(AIProposalReview.created_at.desc(),AIProposalReview.id.desc())).scalar_one_or_none(); return self._read_review(row) if row else None
    def get_run(self,run_id):
        r=self.db.get(AIResearchRun,run_id); return self._read_run(r) if r else None
    def list_runs(self,**f):
        s=select(AIResearchRun)
        cols={"run_type":AIResearchRun.run_type,"status":AIResearchRun.status,"provider":AIResearchRun.provider,"model":AIResearchRun.model_name}
        for k,c in cols.items():
            if f.get(k) is not None:s=s.where(c==f[k])
        for key,col in (("start",AIResearchRun.created_at),("end",AIResearchRun.created_at)):
            if f.get(key):s=s.where(col>=f[key] if key=="start" else col<=f[key])
        rows=self.db.execute(s.order_by(AIResearchRun.created_at.desc(),AIResearchRun.id.desc())).scalars().all()
        def scope_ok(r): return (not f.get("symbol") or f["symbol"].upper() in r.symbol_scope) and (not f.get("strategy") or f["strategy"] in r.strategy_scope) and (not f.get("timeframe") or f["timeframe"] in r.timeframe_scope) and (not f.get("regime") or f["regime"] in r.regime_scope)
        filtered=[x for x in rows if scope_ok(x)]
        off=f.get("offset",0); lim=f.get("limit",100)
        return [self._read_run(x) for x in filtered[off:off+lim]]
    def run_proposals(self,run_id):
        reviews=self.db.execute(select(AIProposalReview).where(AIProposalReview.research_run_id==run_id).order_by(AIProposalReview.overall_score.desc(),AIProposalReview.id.asc())).scalars().all(); return [self.ai._read(self.db.get(AIResearchProposal,x.proposal_id)) for x in reviews]
    @staticmethod
    def _evidence_scope(c): return {k:[str(x["id"]) for x in c[k]] for k in ("observations","outcomes","features","regimes","hypotheses","experiments","candidates","promotion_evaluations")}
    def _invalid_scope(self,p,r):
        refs={"observations":p.referenced_observation_ids,"outcomes":p.referenced_outcome_ids,"hypotheses":p.referenced_hypothesis_ids,"experiments":p.referenced_experiment_ids}; return any(not set(map(str,v)).issubset(set(r.evidence_scope.get(k,[]))) for k,v in refs.items())
    def _evidence_score(self,p,r,min_n):
        refs=len(p.referenced_outcome_ids)+len(p.referenced_observation_ids); n=len(r.evidence_scope.get("outcomes",[])); feature=bool(r.evidence_scope.get("features")); regime=bool(r.evidence_scope.get("regimes")); baseline=bool(r.evidence_scope.get("experiments")); score=min(1.0,0.35*min(1,n/max(1,min_n))+0.25*min(1,refs/max(1,min_n//2))+0.15*feature+0.15*regime+0.10*baseline); return round(score,6),{"outcome_sample":n,"referenced_evidence":refs,"feature_context":feature,"regime_context":regime,"baseline_available":baseline}
    def _novelty_score(self,p):
        sig=self._signature(p); existing=[]
        for q in self.db.execute(select(AIResearchProposal).where(AIResearchProposal.id!=p.id)).scalars(): existing.append(self._signature(q))
        for h in self.db.execute(select(ResearchHypothesis)).scalars(): existing.append(self._norm(f"{h.hypothesis_type} {h.title} {h.description} {h.feature_conditions} {h.entry_conditions} {h.exit_conditions}"))
        if not existing:return 1.0,{"similar_count":0}
        a=set(sig.split()); sims=[len(a&set(x.split()))/max(1,len(a|set(x.split()))) for x in existing]; m=max(sims); return round(max(0,1-m),6),{"max_similarity":round(m,6),"compared":len(existing)}
    def _testability_score(self,p):
        components=[bool(p.feature_conditions),bool(p.entry_conditions),bool(p.exit_conditions),bool(p.parameter_suggestions),bool(p.symbol),bool(p.timeframe),bool(p.regime)]; base=sum(components)/len(components); text=f"{p.hypothesis_statement} {p.summary}".lower(); vague=any(x in text for x in ("guaranteed","always wins","sure profit","somehow","maybe profitable")); score=max(0,base-(0.5 if vague else 0)); return round(score,6),{"explicit_components":sum(components),"vague_penalty":vague}
    def _data_quality_score(self,p,r,min_n):
        outcomes=len(r.evidence_scope.get("outcomes",[])); features=len(r.evidence_scope.get("features",[])); regimes=len(r.evidence_scope.get("regimes",[])); execution=sum(1 for oid in p.referenced_outcome_ids if oid); score=0.45*min(1,outcomes/max(1,min_n))+0.20*min(1,features/max(1,min_n//2))+0.20*min(1,regimes/max(1,min_n//2))+0.15*(1 if execution else 0); return round(score,6),{"outcomes":outcomes,"features":features,"regimes":regimes,"execution_refs":execution}
    def _safety_score(self,p):
        blob=self._norm(f"{p.title} {p.summary} {p.hypothesis_statement} {p.rationale} {p.feature_conditions} {p.entry_conditions} {p.exit_conditions} {p.risk_conditions} {p.parameter_suggestions}"); violations=[k for k,pat in CRITICAL_PATTERNS.items() if re.search(pat,blob,re.I)]; return (0.0 if violations else 1.0),{"violations":violations}
    def _economic_relevance(self,p,r):
        return round(min(1.0,(len(p.referenced_outcome_ids)+len(r.evidence_scope.get("outcomes",[])))/50),6)
    @staticmethod
    def _norm(x): return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9_./:-]+"," ",str(x).lower())).strip()
    def _signature(self,p): return self._norm(f"{p.proposal_type} {p.hypothesis_statement} {p.feature_conditions} {p.entry_conditions} {p.exit_conditions} {p.risk_conditions} {p.parameter_suggestions} {p.symbol} {p.timeframe} {p.regime}")
    def _observe(self,event,run,proposal=None,review=None):
        ctx={"run_id":str(run.id),"run_type":run.run_type,"status":run.status,"provider":run.provider,"model":run.model_name}
        if proposal:ctx.update({"proposal_id":str(proposal.id),"proposal_type":proposal.proposal_type,"proposal_status":proposal.status})
        if review:ctx.update({"review_id":str(review.id),"overall_score":str(review.overall_score),"suppressed":review.suppressed,"rejection_reasons":review.rejection_reasons})
        observe_best_effort(self.db, ObservationCreate(event_type=event,source="ai_research_orchestrator",symbol=proposal.symbol if proposal else None,timeframe=proposal.timeframe if proposal else None,strategy_name=proposal.strategy_name if proposal else None,context=ctx))
    @staticmethod
    def _sanitize_error(exc):
        msg=str(exc); return "AI research run failed" if any(x in msg.lower() for x in ("api key","secret","credential")) else msg[:500]
    @staticmethod
    def _read_run(x): return AIResearchRunRead(**{k:getattr(x,k) for k in AIResearchRunRead.model_fields})
    @staticmethod
    def _read_review(x): return AIProposalReviewRead(**{k:getattr(x,k) for k in AIProposalReviewRead.model_fields})
