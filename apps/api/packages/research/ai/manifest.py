from __future__ import annotations

import os, re, uuid, json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    AIStrategyBlueprint, AIStrategyVariant, BlueprintValidationRun,
    CandidatePromotionEvaluation, DemoRuntimeRelease, DemoStrategyManifest,
    ResearchCandidateHandoff, ResearchCandidateStrategy, ResearchMonitoringPolicy,
    ResearchObservation, ResearchTriggerEvent, ShadowResearchSession,
    StrategyRuntimeCompatibilityCheck,
)
from packages.research.ai.schemas import ALLOWED_INDICATORS, ALLOWED_OPERATORS
from packages.research.ai.shadow import canonical_hash

MANIFEST_VERSION="1.0.0"
COMPATIBILITY_CHECK_VERSION="1.0.0"
RELEASE_VERSION="1.0.0"
MANIFEST_STATUSES={"draft","compiled","compatibility_failed","review_required","ready_for_demo_runtime","revoked","archived"}
RELEASE_STATUSES={"draft","ready","revoked","archived"}
SUPPORTED_TIMEFRAMES={"1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w"}
CODE_PATTERNS=("ev"+"al(","ex"+"ec(","import ","__import__","subprocess","os.system","javascript:","function(","=>","#!/")
FUTURE_PATTERNS=("future","next_candle","next candle","lookahead","look-ahead","tomorrow","t+1")
RISK_RELAX_PATTERNS=("disable","bypass","ignore","override","remove","unlimited","no_limit","no limit")
D=Decimal


def _json_safe(value:Any):
    return json.loads(json.dumps(value,default=str))

def _env_float(name:str, default:float, lo:float=0, hi:float=1)->float:
    try:v=float(os.getenv(name,str(default)))
    except Exception:v=default
    return max(lo,min(hi,v))

def _env_bool(name:str,default:bool)->bool:
    return os.getenv(name,str(default).lower()).strip().lower() in {"1","true","yes","on"}

def _walk(v:Any):
    if isinstance(v,dict):
        for k,x in v.items():
            yield str(k);yield from _walk(x)
    elif isinstance(v,(list,tuple)):
        for x in v:yield from _walk(x)
    else:yield str(v)

def _contains(v:Any, patterns)->bool:
    text=" ".join(_walk(v)).lower()
    return any(p.lower() in text for p in patterns)

def _indicators(v:Any)->set[str]:
    out=set()
    if isinstance(v,dict):
        if "indicator" in v:out.add(str(v["indicator"]).lower())
        if "reference" in v and isinstance(v["reference"],str):out.add(v["reference"].lower())
        for x in v.values():out|=_indicators(x)
    elif isinstance(v,list):
        for x in v:out|=_indicators(x)
    return out

def _operators(v:Any)->set[str]:
    out=set()
    if isinstance(v,dict):
        if "operator" in v:out.add(str(v["operator"]))
        for x in v.values():out|=_operators(x)
    elif isinstance(v,list):
        for x in v:out|=_operators(x)
    return out

def _safe_symbol(s:str)->bool:
    return bool(re.fullmatch(r"[A-Z0-9._-]+/[A-Z0-9._-]+",s.upper()))

class CompileRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    candidate_id:uuid.UUID

class ManifestRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:uuid.UUID;candidate_id:uuid.UUID;promotion_evaluation_id:uuid.UUID;handoff_id:uuid.UUID|None
    source_blueprint_id:uuid.UUID|None;source_variant_id:uuid.UUID|None;source_validation_id:uuid.UUID|None;shadow_session_id:uuid.UUID|None
    manifest_version:str;status:str;strategy_name:str;strategy_version:str
    symbol_scope:list[Any];timeframe_scope:list[Any];regime_scope:list[Any];feature_requirements:list[Any];indicator_requirements:list[Any]
    entry_logic:dict[str,Any];exit_logic:dict[str,Any];protection_logic:dict[str,Any];parameter_values:dict[str,Any];risk_constraints:dict[str,Any]
    strategy_protocol_config:dict[str,Any];validation_summary:dict[str,Any];shadow_summary:dict[str,Any];governance_summary:dict[str,Any]
    runtime_requirements:dict[str,Any];runtime_compatibility:dict[str,Any];warnings:list[Any];blocking_reasons:list[Any]
    configuration:dict[str,Any];configuration_hash:str;supersedes_manifest_id:uuid.UUID|None;compiled_at:datetime;updated_at:datetime

class CompatibilityRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:uuid.UUID;manifest_id:uuid.UUID;check_version:str;status:str;strategy_protocol_compatible:bool;feature_compatible:bool;indicator_compatible:bool;timeframe_compatible:bool;market_data_compatible:bool;protection_compatible:bool;risk_boundary_compatible:bool;deterministic_logic_compatible:bool;overall_score:Decimal;checks:dict[str,Any];warnings:list[Any];blocking_reasons:list[Any];configuration:dict[str,Any];configuration_hash:str;checked_at:datetime

class ReleaseRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:uuid.UUID;manifest_id:uuid.UUID;candidate_id:uuid.UUID;compatibility_check_id:uuid.UUID;release_version:str;status:str;release_notes:dict[str,Any];governance_snapshot:dict[str,Any];safety_snapshot:dict[str,Any];configuration:dict[str,Any];configuration_hash:str;created_at:datetime;revoked_at:datetime|None

class DemoManifestService:
    """Research/runtime handoff compiler. Deliberately has no execution, bot, exchange or credential dependencies."""
    def __init__(self,db:Session):self.db=db

    def _promotion(self,candidate_id):
        return self.db.execute(select(CandidatePromotionEvaluation).where(CandidatePromotionEvaluation.candidate_id==candidate_id).order_by(CandidatePromotionEvaluation.evaluated_at.desc(),CandidatePromotionEvaluation.id.desc()).limit(1)).scalar_one_or_none()
    def _manifest(self,id):return self.db.get(DemoStrategyManifest,id)
    def _check(self,manifest_id):return self.db.execute(select(StrategyRuntimeCompatibilityCheck).where(StrategyRuntimeCompatibilityCheck.manifest_id==manifest_id).order_by(StrategyRuntimeCompatibilityCheck.checked_at.desc(),StrategyRuntimeCompatibilityCheck.id.desc()).limit(1)).scalar_one_or_none()
    def _handoff(self,candidate_id):return self.db.execute(select(ResearchCandidateHandoff).where(ResearchCandidateHandoff.created_candidate_id==candidate_id).order_by(ResearchCandidateHandoff.created_at.desc(),ResearchCandidateHandoff.id.desc()).limit(1)).scalar_one_or_none()

    def compile(self,request:CompileRequest)->ManifestRead:
        c=self.db.get(ResearchCandidateStrategy,request.candidate_id)
        if not c:raise LookupError("candidate not found")
        p=self._promotion(c.id)
        if c.status!="approved_for_demo":raise ValueError("candidate must already be approved_for_demo through Phase-3 governance")
        if not p or not p.overall_passed or p.failure_reasons:raise ValueError("passing CandidatePromotionEvaluation is required")
        h=self._handoff(c.id);bp=v=val=shadow=None
        if h:
            bp=self.db.get(AIStrategyBlueprint,h.blueprint_id) if h.blueprint_id else None
            v=self.db.get(AIStrategyVariant,h.variant_id) if h.variant_id else None
            val=self.db.get(BlueprintValidationRun,h.validation_id) if h.validation_id else None
            shadow=self.db.get(ShadowResearchSession,h.shadow_session_id) if h.shadow_session_id else None
            sd=h.strategy_definition or {};entry=sd.get("entry_logic") or {};exit_=sd.get("exit_logic") or {};protection=sd.get("protection_logic") or h.protection_requirements or {};features=sd.get("feature_requirements") or [];indicators=sd.get("indicator_requirements") or [];params=h.parameter_values or {};risk=h.risk_constraints or {};symbols=h.symbol_scope or [];tfs=h.timeframe_scope or [];regimes=h.regime_scope or []
        else:
            entry=c.entry_conditions or {};exit_=c.exit_conditions or {};protection=(c.configuration or {}).get("protection_logic",{}) or {};features=list((c.feature_conditions or {}).keys());indicators=sorted(_indicators({"entry":entry,"exit":exit_}));params=c.parameter_overrides or {};risk=c.risk_conditions or {};symbols=(c.symbol_scope or {}).get("symbols",[]);tfs=(c.timeframe_scope or {}).get("timeframes",[]);regimes=(c.regime_scope or {}).get("regimes",[])
        lineage={"candidate_id":str(c.id),"promotion_evaluation_id":str(p.id),"handoff_id":str(h.id) if h else None,"blueprint_id":str(bp.id) if bp else None,"variant_id":str(v.id) if v else None,"validation_id":str(val.id) if val else None,"shadow_session_id":str(shadow.id) if shadow else None,"source_hypothesis_id":str(c.source_hypothesis_id),"source_experiment_id":str(c.source_experiment_id)}
        protocol={"contract":"StrategyOrderProposal","contract_module":"packages.risk.models","strategy_identifier":c.base_strategy_name or c.name,"strategy_version":c.candidate_version,"symbol_scope":symbols,"timeframes":tfs,"required_feature_version":"1.0.0","regime_requirements":regimes,"entry_rule_reference":"manifest.entry_logic","exit_rule_reference":"manifest.exit_logic","parameter_values":params,"proposal_side_rules":{"allowed":["BUY","SELL"],"quantity_in_strategy_proposal":False,"risk_engine_sets_approved_quantity":True},"protection_requirements":protection,"closed_candles_only":True,"risk_engine_final_authority":True}
        governance={"candidate_status":c.status,"promotion_evaluation_id":str(p.id),"promotion_overall_passed":p.overall_passed,"promotion_gate_version":p.gate_version,"approved_for_demo_at":c.updated_at.isoformat() if c.updated_at else None,"research_governance_only":True}
        config={"manifest_version":MANIFEST_VERSION,"candidate_id":str(c.id),"candidate_version":c.candidate_version,"candidate_configuration_hash":c.configuration_hash,"promotion_evaluation_id":str(p.id),"promotion_configuration_hash":p.configuration_hash,"lineage":lineage,"strategy":{"entry":entry,"exit":exit_,"protection":protection,"parameters":params,"risk":risk,"features":features,"indicators":indicators,"symbols":symbols,"timeframes":tfs,"regimes":regimes},"protocol":protocol}
        hsh=canonical_hash(config)
        existing=self.db.execute(select(DemoStrategyManifest).where(DemoStrategyManifest.candidate_id==c.id,DemoStrategyManifest.manifest_version==MANIFEST_VERSION,DemoStrategyManifest.configuration_hash==hsh)).scalar_one_or_none()
        if existing:return ManifestRead.model_validate(existing)
        prev=self.db.execute(select(DemoStrategyManifest).where(DemoStrategyManifest.candidate_id==c.id).order_by(DemoStrategyManifest.compiled_at.desc(),DemoStrategyManifest.id.desc()).limit(1)).scalar_one_or_none()
        row=DemoStrategyManifest(candidate_id=c.id,promotion_evaluation_id=p.id,handoff_id=h.id if h else None,source_blueprint_id=bp.id if bp else None,source_variant_id=v.id if v else None,source_validation_id=val.id if val else None,shadow_session_id=shadow.id if shadow else None,manifest_version=MANIFEST_VERSION,status="compiled",strategy_name=c.base_strategy_name or c.name,strategy_version=c.candidate_version,symbol_scope=symbols,timeframe_scope=tfs,regime_scope=regimes,feature_requirements=features,indicator_requirements=indicators,entry_logic=entry,exit_logic=exit_,protection_logic=protection,parameter_values=params,risk_constraints=risk,strategy_protocol_config=protocol,validation_summary={"id":str(val.id),"passed":val.passed,"score":str(val.score),"stability":str(val.stability_score),"data_quality":str(val.data_quality_score),"overfit_risk":str(val.overfit_risk_score)} if val else {},shadow_summary={"id":str(shadow.id),"readiness":str(shadow.readiness_score),"drift":shadow.drift_metrics} if shadow else {},governance_summary=governance,runtime_requirements={"closed_candles_only":True,"order_proposal_contract":"StrategyOrderProposal","risk_engine_required":True,"mandatory_protection":True},runtime_compatibility={},warnings=[],blocking_reasons=[],configuration=config,configuration_hash=hsh,supersedes_manifest_id=prev.id if prev else None,compiled_at=datetime.now(timezone.utc))
        self.db.add(row);self.db.commit();self.db.refresh(row);self._observe("ai_demo_manifest_compiled",row,{"candidate_id":str(c.id),"promotion_evaluation_id":str(p.id),"status":row.status});return ManifestRead.model_validate(row)

    def check_compatibility(self,manifest_id:uuid.UUID)->CompatibilityRead:
        m=self._manifest(manifest_id)
        if not m:raise LookupError("manifest not found")
        if m.status in {"revoked","archived"}:raise ValueError("revoked/archived manifest cannot be checked")
        inds=set(x.lower() for x in m.indicator_requirements)|_indicators({"entry":m.entry_logic,"exit":m.exit_logic})
        ops=_operators({"entry":m.entry_logic,"exit":m.exit_logic})
        checks={}
        checks["strategy_protocol_compatible"]=m.strategy_protocol_config.get("contract")=="StrategyOrderProposal" and m.strategy_protocol_config.get("risk_engine_final_authority") is True and m.strategy_protocol_config.get("proposal_side_rules",{}).get("quantity_in_strategy_proposal") is False
        checks["feature_compatible"]=all(isinstance(x,str) and len(x)<=128 for x in m.feature_requirements)
        checks["indicator_compatible"]=all(x in ALLOWED_INDICATORS for x in inds)
        checks["timeframe_compatible"]=bool(m.timeframe_scope) and all(x in SUPPORTED_TIMEFRAMES for x in m.timeframe_scope)
        checks["market_data_compatible"]=bool(m.symbol_scope) and all(_safe_symbol(x) for x in m.symbol_scope) and m.runtime_requirements.get("closed_candles_only") is True
        checks["protection_compatible"]=bool(m.protection_logic) and not _contains(m.protection_logic,("disable","bypass","none","no_stop","no stop"))
        checks["risk_boundary_compatible"]=not _contains(m.risk_constraints,RISK_RELAX_PATTERNS) and m.strategy_protocol_config.get("risk_engine_final_authority") is True
        checks["deterministic_logic_compatible"]=not _contains({"entry":m.entry_logic,"exit":m.exit_logic,"protection":m.protection_logic},CODE_PATTERNS+FUTURE_PATTERNS) and all(x in ALLOWED_OPERATORS for x in ops)
        blockers=[name for name,ok in checks.items() if not ok]
        score=D(str(round(sum(1 for x in checks.values() if x)/len(checks),8)))
        cfg={"check_version":COMPATIBILITY_CHECK_VERSION,"manifest_hash":m.configuration_hash,"minimum_score":_env_float("AI_DEMO_MANIFEST_MIN_COMPATIBILITY_SCORE",.80),"checks":checks}
        hsh=canonical_hash(cfg)
        existing=self.db.execute(select(StrategyRuntimeCompatibilityCheck).where(StrategyRuntimeCompatibilityCheck.manifest_id==m.id,StrategyRuntimeCompatibilityCheck.check_version==COMPATIBILITY_CHECK_VERSION,StrategyRuntimeCompatibilityCheck.configuration_hash==hsh)).scalar_one_or_none()
        if existing:return CompatibilityRead.model_validate(existing)
        status="passed" if not blockers and float(score)>=cfg["minimum_score"] else "failed"
        row=StrategyRuntimeCompatibilityCheck(manifest_id=m.id,check_version=COMPATIBILITY_CHECK_VERSION,status=status,strategy_protocol_compatible=checks["strategy_protocol_compatible"],feature_compatible=checks["feature_compatible"],indicator_compatible=checks["indicator_compatible"],timeframe_compatible=checks["timeframe_compatible"],market_data_compatible=checks["market_data_compatible"],protection_compatible=checks["protection_compatible"],risk_boundary_compatible=checks["risk_boundary_compatible"],deterministic_logic_compatible=checks["deterministic_logic_compatible"],overall_score=score,checks=checks,warnings=[],blocking_reasons=blockers,configuration=cfg,configuration_hash=hsh,checked_at=datetime.now(timezone.utc))
        self.db.add(row);m.runtime_compatibility={"check_id":None,"score":str(score),"status":status,"checks":checks};m.status="compiled" if status=="passed" else "compatibility_failed";self.db.commit();self.db.refresh(row);m.runtime_compatibility["check_id"]=str(row.id);self.db.commit();self._observe("ai_demo_manifest_compatibility_checked",m,{"compatibility_check_id":str(row.id),"status":status,"score":str(score),"blocking_reasons":blockers});
        if blockers:self._observe("ai_demo_manifest_blocked",m,{"blocking_reasons":blockers})
        return CompatibilityRead.model_validate(row)

    def _severe_triggers(self,m):
        if not _env_bool("AI_DEMO_RELEASE_BLOCK_SEVERE_TRIGGERS",True):return []
        policies=self.db.execute(select(ResearchMonitoringPolicy).where(ResearchMonitoringPolicy.candidate_id==m.candidate_id)).scalars().all();pids=[p.id for p in policies]
        q=select(ResearchTriggerEvent).where(ResearchTriggerEvent.status.in_(["detected","queued","processing"]),ResearchTriggerEvent.severity_score>=D("0.80"))
        if pids:q=q.where(ResearchTriggerEvent.policy_id.in_(pids))
        else:return []
        return self.db.execute(q.order_by(ResearchTriggerEvent.detected_at.desc())).scalars().all()

    def readiness(self,manifest_id):
        m=self._manifest(manifest_id)
        if not m:raise LookupError("manifest not found")
        c=self.db.get(ResearchCandidateStrategy,m.candidate_id);p=self.db.get(CandidatePromotionEvaluation,m.promotion_evaluation_id);chk=self._check(m.id);severe=self._severe_triggers(m)
        blockers=[]
        if not c or c.status!="approved_for_demo":blockers.append("candidate_governance_not_approved")
        if not p or not p.overall_passed or p.failure_reasons:blockers.append("promotion_evaluation_invalid")
        if not chk or chk.status!="passed":blockers.append("compatibility_not_passed")
        minc=_env_float("AI_DEMO_MANIFEST_MIN_COMPATIBILITY_SCORE",.80);minr=_env_float("AI_DEMO_RELEASE_MIN_READINESS_SCORE",.75)
        if chk and float(chk.overall_score)<minc:blockers.append("compatibility_score_below_threshold")
        if severe:blockers.append("unresolved_severe_monitoring_trigger")
        validation=float(m.validation_summary.get("score",1) or 1);quality=float(m.validation_summary.get("data_quality",1) or 1);stability=float(m.validation_summary.get("stability",1) or 1);overfit=float(m.validation_summary.get("overfit_risk",0) or 0);shadow=float(m.shadow_summary.get("readiness",1) or 1);compat=float(chk.overall_score) if chk else 0
        score=max(0,min(1,.25*compat+.15*validation+.15*quality+.10*stability+.10*(1-overfit)+.10*shadow+.15*(1 if not severe else 0)))
        if score<minr:blockers.append("release_readiness_below_threshold")
        return {"manifest_id":m.id,"candidate_id":m.candidate_id,"status":m.status,"readiness_score":round(score,8),"minimum_readiness_score":minr,"minimum_compatibility_score":minc,"severe_monitoring_trigger_ids":[x.id for x in severe],"blocking_reasons":sorted(set(blockers)),"demo_readiness_does_not_mean_demo_activation":True,"risk_engine_final_authority":True}

    def request_review(self,manifest_id):
        m=self._manifest(manifest_id)
        if not m:raise LookupError("manifest not found")
        if m.status!="compiled":raise ValueError("manifest must be compiled with passing compatibility before review")
        chk=self._check(m.id)
        if not chk or chk.status!="passed":raise ValueError("passing compatibility check required")
        m.status="review_required";self.db.commit();self._observe("ai_demo_manifest_review_requested",m,{"status":m.status});return ManifestRead.model_validate(m)

    def release(self,manifest_id)->ReleaseRead:
        m=self._manifest(manifest_id)
        if not m:raise LookupError("manifest not found")
        if m.status not in {"review_required","ready_for_demo_runtime"}:raise ValueError("explicit manifest review is required before release")
        ready=self.readiness(m.id)
        if ready["blocking_reasons"]:raise ValueError("release blocked: "+", ".join(ready["blocking_reasons"]))
        chk=self._check(m.id);c=self.db.get(ResearchCandidateStrategy,m.candidate_id);p=self.db.get(CandidatePromotionEvaluation,m.promotion_evaluation_id)
        cfg={"release_version":RELEASE_VERSION,"manifest_id":str(m.id),"manifest_hash":m.configuration_hash,"candidate_id":str(c.id),"candidate_status":c.status,"promotion_evaluation_id":str(p.id),"compatibility_check_id":str(chk.id),"compatibility_hash":chk.configuration_hash,"gate_configuration":{"minimum_compatibility":_env_float("AI_DEMO_MANIFEST_MIN_COMPATIBILITY_SCORE",.80),"minimum_readiness":_env_float("AI_DEMO_RELEASE_MIN_READINESS_SCORE",.75),"block_severe_triggers":_env_bool("AI_DEMO_RELEASE_BLOCK_SEVERE_TRIGGERS",True)}}
        hsh=canonical_hash(cfg);existing=self.db.execute(select(DemoRuntimeRelease).where(DemoRuntimeRelease.manifest_id==m.id,DemoRuntimeRelease.release_version==RELEASE_VERSION,DemoRuntimeRelease.configuration_hash==hsh)).scalar_one_or_none()
        if existing:return ReleaseRead.model_validate(existing)
        m.status="ready_for_demo_runtime"
        row=DemoRuntimeRelease(manifest_id=m.id,candidate_id=c.id,compatibility_check_id=chk.id,release_version=RELEASE_VERSION,status="ready",release_notes={"semantics":"governance_runtime_handoff_only_no_activation"},governance_snapshot={**m.governance_summary,"candidate_status":c.status,"promotion_evaluation_id":str(p.id),"compatibility_check_id":str(chk.id),"readiness":_json_safe(ready)},safety_snapshot={"risk_engine_final_authority":True,"starts_bot":False,"submits_order":False,"allocates_capital":False,"decrypts_credentials":False,"live_approval":False},configuration=cfg,configuration_hash=hsh)
        self.db.add(row);self.db.commit();self.db.refresh(row);self._observe("ai_demo_manifest_ready",m,{"status":m.status,"readiness_score":ready["readiness_score"]});self._observe("ai_demo_runtime_release_created",m,{"release_id":str(row.id),"release_status":row.status});return ReleaseRead.model_validate(row)

    def revoke(self,manifest_id):
        m=self._manifest(manifest_id)
        if not m:raise LookupError("manifest not found")
        m.status="revoked";now=datetime.now(timezone.utc)
        rows=self.db.execute(select(DemoRuntimeRelease).where(DemoRuntimeRelease.manifest_id==m.id,DemoRuntimeRelease.status=="ready")).scalars().all()
        for r in rows:r.status="revoked";r.revoked_at=now
        self.db.commit();self._observe("ai_demo_runtime_release_revoked",m,{"release_ids":[str(x.id) for x in rows],"semantics":"metadata_revocation_only_no_bot_command"});return ManifestRead.model_validate(m)

    def runtime_contract(self,manifest_id):
        m=self._manifest(manifest_id)
        if not m:raise LookupError("manifest not found")
        chk=self._check(m.id)
        return {"manifest":{"id":m.id,"version":m.manifest_version,"status":m.status,"configuration_hash":m.configuration_hash},"strategy":{"name":m.strategy_name,"version":m.strategy_version},"symbol_scope":m.symbol_scope,"timeframe_scope":m.timeframe_scope,"regime_scope":m.regime_scope,"feature_requirements":m.feature_requirements,"indicator_requirements":m.indicator_requirements,"entry_logic":m.entry_logic,"exit_logic":m.exit_logic,"parameters":m.parameter_values,"protection_requirements":m.protection_logic,"risk_hints":m.risk_constraints,"strategy_protocol_config":m.strategy_protocol_config,"compatibility":{"status":chk.status if chk else "not_checked","score":chk.overall_score if chk else None},"execution_authority":False,"risk_engine_final_authority":True,"contains_credentials":False,"bot_start_command":None,"capital_allocation":None}

    def lineage(self,manifest_id):
        m=self._manifest(manifest_id)
        if not m:raise LookupError("manifest not found")
        return {"manifest_id":m.id,"candidate_id":m.candidate_id,"promotion_evaluation_id":m.promotion_evaluation_id,"handoff_id":m.handoff_id,"blueprint_id":m.source_blueprint_id,"variant_id":m.source_variant_id,"validation_id":m.source_validation_id,"shadow_session_id":m.shadow_session_id,"source_hypothesis_id":m.configuration.get("lineage",{}).get("source_hypothesis_id"),"source_experiment_id":m.configuration.get("lineage",{}).get("source_experiment_id"),"fabricated_lineage":False}

    def manifests(self,candidate=None,blueprint=None,variant=None,status=None,symbol=None,timeframe=None,regime=None,minimum_compatibility=None,limit=100,offset=0):
        q=select(DemoStrategyManifest)
        if candidate:q=q.where(DemoStrategyManifest.candidate_id==candidate)
        if blueprint:q=q.where(DemoStrategyManifest.source_blueprint_id==blueprint)
        if variant:q=q.where(DemoStrategyManifest.source_variant_id==variant)
        if status:q=q.where(DemoStrategyManifest.status==status)
        rows=self.db.execute(q.order_by(DemoStrategyManifest.compiled_at.desc(),DemoStrategyManifest.id.desc())).scalars().all()
        if symbol:rows=[r for r in rows if symbol.upper() in [str(x).upper() for x in r.symbol_scope]]
        if timeframe:rows=[r for r in rows if timeframe in r.timeframe_scope]
        if regime:rows=[r for r in rows if regime in r.regime_scope]
        if minimum_compatibility is not None:rows=[r for r in rows if float((r.runtime_compatibility or {}).get("score",0) or 0)>=float(minimum_compatibility)]
        return [ManifestRead.model_validate(r) for r in rows[offset:offset+limit]]
    def manifest(self,id):
        r=self._manifest(id);return ManifestRead.model_validate(r) if r else None
    def compatibility(self,id):
        r=self._check(id);return CompatibilityRead.model_validate(r) if r else None
    def releases(self,status=None,limit=100,offset=0):
        q=select(DemoRuntimeRelease)
        if status:q=q.where(DemoRuntimeRelease.status==status)
        rows=self.db.execute(q.order_by(DemoRuntimeRelease.created_at.desc(),DemoRuntimeRelease.id.desc()).offset(offset).limit(limit)).scalars().all();return [ReleaseRead.model_validate(r) for r in rows]
    def release_get(self,id):
        r=self.db.get(DemoRuntimeRelease,id);return ReleaseRead.model_validate(r) if r else None
    def _observe(self,event_type,m,context):
        obs=ResearchObservation(event_type=event_type,source="research.ai.demo_manifest",symbol=(m.symbol_scope or [None])[0] if m.symbol_scope else None,timeframe=(m.timeframe_scope or [None])[0] if m.timeframe_scope else None,strategy_name=m.strategy_name,context={"manifest_id":str(m.id),"candidate_id":str(m.candidate_id),"regime":(m.regime_scope or [None])[0] if len(m.regime_scope)==1 else None,**context},observed_at=datetime.now(timezone.utc))
        self.db.add(obs);self.db.commit();return obs
