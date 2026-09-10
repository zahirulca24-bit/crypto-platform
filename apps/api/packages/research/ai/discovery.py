from __future__ import annotations
import hashlib, json, math, os, re
from decimal import Decimal
from typing import Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models import AIResearchProposal, AIProposalReview, AIStrategyBlueprint, ResearchExperiment, ResearchHypothesis
from packages.research.models import ObservationCreate
from packages.research.service import ResearchObservationService
from .gemini_provider import GeminiResearchProvider, AIProviderNotConfigured
from .provider import ResearchAIProvider
from .prompts import build_strategy_discovery_prompt
from .safety import sanitize_context
from .schemas import (ALLOWED_INDICATORS,BLUEPRINT_STATUSES,BLUEPRINT_VERSION,BlueprintGenerateRequest,BlueprintRead,STRATEGY_DISCOVERY_PROMPT_VERSION,StructuredStrategyBlueprint)

CODE_PATTERNS=(r"\beval\s*\(",r"\bexec\s*\(",r"\bimport\s+[a-z_]",r"\bsubprocess\b",r"\bos\.system\b",r"```",r"\bfunction\s*\(",r"=>",r"#!/")
FUTURE_PATTERNS=("future","next candle","tomorrow","lookahead","look-ahead","future candle")
RISK_BLOCK_PATTERNS=("disable stop","no stop loss","remove stop","bypass risk","disable risk","override daily loss","disable kill switch","approved_for_live","enable live","submit order","api key","credential","withdraw")

def canonical_hash(value:Any)->str:return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

def _env_int(name,default,lo,hi):
    try:v=int(os.getenv(name,str(default)))
    except ValueError:return default
    return max(lo,min(hi,v))
def _env_float(name,default,lo,hi):
    try:v=float(os.getenv(name,str(default)))
    except ValueError:return default
    return max(lo,min(hi,v))

class StrategyDiscoveryService:
    """Research-only blueprint discovery. Deliberately has no trading/execution dependencies."""
    def __init__(self,db:Session,provider:ResearchAIProvider|None=None): self.db=db; self.provider=provider or GeminiResearchProvider()
    def generate(self,req:BlueprintGenerateRequest)->BlueprintRead:
        sources=self._sources(req); context=self._context(sources); prompt=build_strategy_discovery_prompt(context)
        if not self.provider.configured: raise AIProviderNotConfigured("AI research provider is not configured")
        payload,metadata=self.provider.generate_strategy_blueprint(context=context,prompt=prompt)
        bp=StructuredStrategyBlueprint.model_validate(payload); return self._persist(bp,req,sources,context,metadata)
    def _sources(self,req):
        if not any((req.source_ai_proposal_id,req.source_hypothesis_id,req.source_experiment_id)): raise ValueError("at least one persisted research source is required")
        p=r=h=e=None
        if req.source_ai_proposal_id:
            p=self.db.get(AIResearchProposal,req.source_ai_proposal_id)
            if not p: raise LookupError("AI research proposal not found")
            r=self.db.execute(select(AIProposalReview).where(AIProposalReview.proposal_id==p.id).order_by(AIProposalReview.created_at.desc(),AIProposalReview.id.desc())).scalar_one_or_none()
            if p.status not in {"review_required","accepted_for_research","converted"} or not r or r.suppressed or not r.accepted_for_review: raise ValueError("AI proposal must pass deterministic review before strategy discovery")
        if req.source_hypothesis_id:
            h=self.db.get(ResearchHypothesis,req.source_hypothesis_id)
            if not h: raise LookupError("Research hypothesis not found")
        if req.source_experiment_id:
            e=self.db.get(ResearchExperiment,req.source_experiment_id)
            if not e: raise LookupError("Research experiment not found")
            if e.status!="completed": raise ValueError("Research experiment must be completed")
            if h is None:h=self.db.get(ResearchHypothesis,e.hypothesis_id)
        parent=self.db.get(AIStrategyBlueprint,req.parent_blueprint_id) if req.parent_blueprint_id else None
        if req.parent_blueprint_id and not parent: raise LookupError("Parent blueprint not found")
        return {"proposal":p,"review":r,"hypothesis":h,"experiment":e,"parent":parent}
    def _context(self,s):
        p,r,h,e=s["proposal"],s["review"],s["hypothesis"],s["experiment"]
        data={"source_ids":{"proposal":str(p.id) if p else None,"review":str(r.id) if r else None,"hypothesis":str(h.id) if h else None,"experiment":str(e.id) if e else None},"proposal":None,"review":None,"hypothesis":None,"experiment":None}
        if p:data["proposal"]={"type":p.proposal_type,"title":p.title,"summary":p.summary,"hypothesis_statement":p.hypothesis_statement,"feature_conditions":p.feature_conditions,"entry_conditions":p.entry_conditions,"exit_conditions":p.exit_conditions,"risk_conditions":p.risk_conditions,"parameter_suggestions":p.parameter_suggestions,"evidence":p.supporting_evidence,"data_scope":p.data_scope,"symbol":p.symbol,"timeframe":p.timeframe,"regime":p.regime,"strategy":p.strategy_name}
        if r:data["review"]={"evidence_score":str(r.evidence_score),"novelty_score":str(r.novelty_score),"testability_score":str(r.testability_score),"data_quality_score":str(r.data_quality_score),"safety_score":str(r.safety_score),"overall_score":str(r.overall_score),"warnings":r.warnings}
        if h:data["hypothesis"]={"type":h.hypothesis_type,"title":h.title,"description":h.description,"feature_conditions":h.feature_conditions,"entry_conditions":h.entry_conditions,"exit_conditions":h.exit_conditions,"risk_conditions":h.risk_conditions,"evidence_summary":h.evidence_summary,"source_metrics":h.source_metrics,"sample_size":h.sample_size,"confidence_score":str(h.confidence_score),"priority_score":str(h.priority_score),"symbol":h.symbol,"timeframe":h.timeframe,"regime":h.regime,"strategy":h.strategy_name,"version":h.hypothesis_version,"hash":h.configuration_hash}
        if e:data["experiment"]={"type":e.experiment_type,"status":e.status,"passed":e.passed,"sample_size":e.sample_size,"baseline_sample_size":e.baseline_sample_size,"result_metrics":e.result_metrics,"baseline_metrics":e.baseline_metrics,"comparison_metrics":e.comparison_metrics,"score":str(e.score),"stability_score":str(e.stability_score),"data_quality_score":str(e.data_quality_score),"failure_reasons":e.failure_reasons,"historical_scope":{"train_start":e.train_start,"train_end":e.train_end,"validation_start":e.validation_start,"validation_end":e.validation_end},"configuration_hash":e.configuration_hash}
        return sanitize_context(data)
    def _persist(self,bp,req,s,context,metadata):
        warnings,blockers=self._validate(bp); combinations=self._parameter_combinations(bp.parameter_space); maxcomb=_env_int("AI_BLUEPRINT_MAX_PARAMETER_COMBINATIONS",500,1,100000)
        if combinations>maxcomb:blockers.append("parameter_search_space_exceeds_limit")
        condition_count=len(bp.entry_logic.all)+len(bp.entry_logic.any)+self._exit_condition_count(bp.exit_logic); maxconds=_env_int("AI_BLUEPRINT_MAX_CONDITIONS",20,1,100)
        if condition_count>maxconds:blockers.append("condition_count_exceeds_limit")
        complexity=self._complexity(len(set(bp.indicator_requirements)),condition_count,len(bp.parameter_space),combinations,len(bp.regime_scope))
        if complexity=="excessive":warnings.append("excessive_complexity"); blockers.append("excessive_complexity")
        readiness=self._readiness(s,bp,blockers,combinations,maxcomb,condition_count,maxconds)
        if readiness<_env_float("AI_BLUEPRINT_MIN_READINESS_SCORE",0.65,0,1):warnings.append("readiness_below_acceptance_threshold")
        evidence_scope={"source_ids":context["source_ids"],"proposal_data_scope":s["proposal"].data_scope if s["proposal"] else {},"experiment_scope":context.get("experiment",{}).get("historical_scope") if context.get("experiment") else None}
        evidence_summary={"review":context.get("review"),"hypothesis":context.get("hypothesis"),"experiment":context.get("experiment"),"provider_metadata":sanitize_context(metadata)}
        normalized=bp.model_dump(mode="json"); cfg={"blueprint_version":BLUEPRINT_VERSION,"prompt_version":STRATEGY_DISCOVERY_PROMPT_VERSION,"provider":self.provider.provider_name,"model":self.provider.model_name,"source_evidence_scope":evidence_scope,"entry_logic":normalized["entry_logic"],"exit_logic":normalized["exit_logic"],"protection_logic":normalized["protection_logic"],"risk_constraints":normalized["risk_constraints"],"parameter_space":normalized["parameter_space"],"symbol_scope":normalized["symbol_scope"],"timeframe_scope":normalized["timeframe_scope"],"regime_scope":normalized["regime_scope"],"parent_blueprint_id":str(req.parent_blueprint_id) if req.parent_blueprint_id else None}
        h=canonical_hash(cfg); existing=self.db.execute(select(AIStrategyBlueprint).where(AIStrategyBlueprint.blueprint_version==BLUEPRINT_VERSION,AIStrategyBlueprint.prompt_version==STRATEGY_DISCOVERY_PROMPT_VERSION,AIStrategyBlueprint.configuration_hash==h)).scalar_one_or_none()
        if existing:return self._read(existing)
        row=AIStrategyBlueprint(name=bp.name,description=bp.description,blueprint_type=bp.blueprint_type,status=("rejected" if blockers else "draft"),source_ai_proposal_id=s["proposal"].id if s["proposal"] else None,source_review_id=s["review"].id if s["review"] else None,source_hypothesis_id=s["hypothesis"].id if s["hypothesis"] else None,source_experiment_id=s["experiment"].id if s["experiment"] else None,base_strategy_name=bp.base_strategy_name or (s["hypothesis"].strategy_name if s["hypothesis"] else None),base_strategy_version=bp.base_strategy_version or (s["hypothesis"].strategy_version if s["hypothesis"] else None),symbol_scope=bp.symbol_scope,timeframe_scope=bp.timeframe_scope,regime_scope=bp.regime_scope,feature_requirements=bp.feature_requirements,indicator_requirements=bp.indicator_requirements,entry_logic=bp.entry_logic.model_dump(mode="json"),exit_logic=bp.exit_logic,protection_logic=bp.protection_logic,risk_constraints=bp.risk_constraints,parameter_space={k:v.model_dump(mode="json") for k,v in bp.parameter_space.items()},expected_behavior=bp.expected_behavior,invalidation_conditions=bp.invalidation_conditions,evidence_summary=evidence_summary,evidence_scope=evidence_scope,estimated_complexity=complexity,estimated_data_requirements={**bp.estimated_data_requirements,"parameter_combinations":combinations,"condition_count":condition_count},readiness_score=Decimal(str(readiness)),warnings=sorted(set(warnings)),blocking_reasons=sorted(set(blockers)),provider=self.provider.provider_name,model_name=self.provider.model_name,prompt_version=STRATEGY_DISCOVERY_PROMPT_VERSION,blueprint_version=BLUEPRINT_VERSION,configuration=cfg,configuration_hash=h,parent_blueprint_id=req.parent_blueprint_id)
        self.db.add(row)
        try:self.db.commit()
        except IntegrityError:self.db.rollback(); row=self.db.execute(select(AIStrategyBlueprint).where(AIStrategyBlueprint.configuration_hash==h)).scalar_one(); return self._read(row)
        self.db.refresh(row); obs=self._observe(row,"ai_strategy_blueprint_generated");
        if blockers: self._observe(row,"ai_strategy_blueprint_rejected")
        row.research_observation_id=obs.event_id; self.db.commit(); self.db.refresh(row); return self._read(row)
    def _validate(self,bp):
        warnings=[]; blockers=[]; blob=json.dumps(bp.model_dump(mode="json"),sort_keys=True).lower()
        if any(re.search(p,blob,re.I) for p in CODE_PATTERNS):blockers.append("executable_code_not_allowed")
        if any(x in blob for x in FUTURE_PATTERNS):blockers.append("future_data_condition_not_allowed")
        if any(x in blob for x in RISK_BLOCK_PATTERNS):blockers.append("risk_or_execution_safety_violation")
        if bp.protection_logic.get("stop_loss_required") is False:blockers.append("mandatory_protection_cannot_be_disabled")
        for k,v in bp.risk_constraints.items():
            if isinstance(v,(int,float)) and (not math.isfinite(float(v)) or abs(float(v))>1000000):blockers.append("unbounded_risk_constraint")
        return warnings,blockers
    @staticmethod
    def _parameter_combinations(space):
        n=1
        for r in space.values():
            if r.values is not None:c=len(r.values)
            elif r.min is not None and r.max is not None and r.step is not None and float(r.step)>0:c=max(1,int(math.floor((float(r.max)-float(r.min))/float(r.step)))+1)
            else:c=1
            if c<1 or c>10000:return 1000000000
            n*=c
            if n>1000000000:return n
        return n
    @staticmethod
    def _exit_condition_count(x): return len(x) if isinstance(x,dict) else 0
    @staticmethod
    def _complexity(indicators,conditions,params,combos,regimes):
        score=indicators+conditions+params*2+(2 if regimes else 0)+(0 if combos<=20 else 4 if combos<=100 else 8 if combos<=500 else 15)
        return "low" if score<=8 else "medium" if score<=18 else "high" if score<=30 else "excessive"
    def _readiness(self,s,bp,blockers,combos,maxcomb,conds,maxconds):
        if blockers:return round(max(0,0.35-0.05*len(blockers)),6)
        evidence=0.4
        if s["review"]: evidence=max(evidence,float(s["review"].overall_score))
        if s["experiment"]: evidence=max(evidence,(float(s["experiment"].score)+float(s["experiment"].data_quality_score)+float(s["experiment"].stability_score))/3)
        elif s["hypothesis"]: evidence=max(evidence,float(s["hypothesis"].confidence_score))
        testability=min(1,(len(bp.entry_logic.all)+len(bp.entry_logic.any)+len(bp.exit_logic)+len(bp.parameter_space))/6)
        data=1.0 if (s["experiment"] and s["experiment"].sample_size>=10) else 0.7 if s["hypothesis"] and s["hypothesis"].sample_size>=5 else 0.45
        bounded=(1-min(1,combos/maxcomb)*0.4)*(1-min(1,conds/maxconds)*0.2)
        return round(max(0,min(1,0.35*evidence+0.3*testability+0.2*data+0.15*bounded)),6)
    def request_review(self,bid):
        row=self._get(bid)
        if row.status!="draft":raise ValueError("blueprint must be draft to request review")
        row.status="review_required"; self.db.commit(); self.db.refresh(row); self._observe(row,"ai_strategy_blueprint_review_requested"); return self._read(row)
    def accept_for_validation(self,bid):
        row=self._get(bid); threshold=_env_float("AI_BLUEPRINT_MIN_READINESS_SCORE",0.65,0,1)
        if row.status!="review_required":raise ValueError("blueprint must be review_required")
        if row.blocking_reasons:raise ValueError("blueprint has blocking safety/readiness reasons")
        if float(row.readiness_score)<threshold:raise ValueError("blueprint readiness score below threshold")
        row.status="accepted_for_validation"; self.db.commit(); self.db.refresh(row); self._observe(row,"ai_strategy_blueprint_accepted_for_validation"); return self._read(row)
    def reject(self,bid):
        row=self._get(bid)
        if row.status=="accepted_for_validation":raise ValueError("accepted blueprint cannot be silently rejected")
        row.status="rejected"; self.db.commit(); self.db.refresh(row); self._observe(row,"ai_strategy_blueprint_rejected"); return self._read(row)
    def get(self,bid):
        row=self.db.get(AIStrategyBlueprint,bid); return self._read(row) if row else None
    def readiness(self,bid):
        row=self._get(bid); return {"blueprint_id":str(row.id),"readiness_score":float(row.readiness_score),"complexity":row.estimated_complexity,"warnings":row.warnings,"blocking_reasons":row.blocking_reasons,"threshold":_env_float("AI_BLUEPRINT_MIN_READINESS_SCORE",0.65,0,1),"accepted_for_validation":row.status=="accepted_for_validation"}
    def list(self,**f):
        q=select(AIStrategyBlueprint)
        for k,col in (("blueprint_type",AIStrategyBlueprint.blueprint_type),("status",AIStrategyBlueprint.status),("base_strategy",AIStrategyBlueprint.base_strategy_name),("source_proposal",AIStrategyBlueprint.source_ai_proposal_id),("source_hypothesis",AIStrategyBlueprint.source_hypothesis_id),("source_experiment",AIStrategyBlueprint.source_experiment_id),("complexity",AIStrategyBlueprint.estimated_complexity)):
            if f.get(k) is not None:q=q.where(col==f[k])
        if f.get("minimum_readiness") is not None:q=q.where(AIStrategyBlueprint.readiness_score>=Decimal(str(f["minimum_readiness"])))
        rows=self.db.execute(q.order_by(AIStrategyBlueprint.created_at.desc(),AIStrategyBlueprint.id.desc())).scalars().all()
        def scope(r):return (not f.get("symbol") or f["symbol"].upper() in r.symbol_scope) and (not f.get("timeframe") or f["timeframe"] in r.timeframe_scope) and (not f.get("regime") or f["regime"] in r.regime_scope)
        rows=[r for r in rows if scope(r)]; off=f.get("offset",0); lim=f.get("limit",100); return [self._read(r) for r in rows[off:off+lim]]
    def _get(self,bid):
        row=self.db.get(AIStrategyBlueprint,bid)
        if not row:raise LookupError("AI strategy blueprint not found")
        return row
    def _observe(self,row,event):
        obs=ResearchObservationService(self.db).record(ObservationCreate(event_type=event,source="ai_strategy_discovery",symbol=row.symbol_scope[0] if row.symbol_scope else None,timeframe=row.timeframe_scope[0] if row.timeframe_scope else None,strategy_name=row.base_strategy_name,context={"blueprint_id":str(row.id),"source_proposal_id":str(row.source_ai_proposal_id) if row.source_ai_proposal_id else None,"source_hypothesis_id":str(row.source_hypothesis_id) if row.source_hypothesis_id else None,"source_experiment_id":str(row.source_experiment_id) if row.source_experiment_id else None,"provider":row.provider,"model":row.model_name,"blueprint_type":row.blueprint_type,"status":row.status,"readiness_score":str(row.readiness_score),"complexity":row.estimated_complexity,"warnings":row.warnings,"blocking_reasons":row.blocking_reasons}))
        return obs
    @staticmethod
    def _read(row):
        d={k:getattr(row,k) for k in BlueprintRead.model_fields}; d["readiness_score"]=float(d["readiness_score"]); return BlueprintRead.model_validate(d)
