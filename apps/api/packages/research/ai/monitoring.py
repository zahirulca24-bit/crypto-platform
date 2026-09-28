from __future__ import annotations

import hashlib, json, os, math
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from models import (
    ResearchMonitoringPolicy, ResearchTriggerEvent, AdaptiveResearchJob, ResearchMonitorWorkerStatus,
    MarketRegimeSnapshot, TradeOutcome, BlueprintValidationRun, ShadowResearchSession,
    ResearchCandidateStrategy, CandidatePromotionEvaluation, ResearchStrategyPortfolio,
)
from packages.research.models import ObservationCreate
from packages.research.service import observe_best_effort

POLICY_VERSION="1.0.0"; TRIGGER_VERSION="1.0.0"; JOB_VERSION="1.0.0"
POLICY_STATUSES={"draft","enabled","paused","disabled","archived"}
TRIGGER_TYPES={
    "regime_change","expectancy_degradation","drawdown_degradation","win_rate_degradation",
    "profit_factor_degradation","execution_cost_drift","slippage_drift","fee_drag_increase",
    "signal_frequency_drift","shadow_performance_drift","strategy_stability_degradation",
    "data_quality_degradation","overfit_risk_increase","candidate_staleness","research_portfolio_degradation",
}
TRIGGER_STATUSES={"detected","suppressed","queued","processing","completed","failed","acknowledged","archived"}
JOB_TYPES={"rerun_ai_research","regenerate_hypotheses","blueprint_review","blueprint_revalidation","strategy_evolution_review","regime_matching_refresh","portfolio_rebuild_review","shadow_readiness_review","candidate_readiness_review"}
JOB_STATUSES={"queued","running","completed","failed","cancelled"}
D=Decimal

def canonical_hash(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

def _f(v,default=0.0):
    try:x=float(v); return x if math.isfinite(x) else default
    except (TypeError,ValueError):return default

def _env_int(name,default,lo=0,hi=1000000):
    try:v=int(os.getenv(name,str(default)))
    except ValueError:v=default
    return max(lo,min(hi,v))

def _env_bool(name,default=False):
    return os.getenv(name,"true" if default else "false").strip().lower() in {"1","true","yes","on"}

def utcnow():return datetime.now(timezone.utc)
def _aware(v):
    if v is None:return None
    return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)

def _serialize_metrics(rows):
    n=len(rows)
    if not n:return {"sample_size":0,"expectancy":0.0,"win_rate":0.0,"profit_factor":0.0,"max_drawdown":0.0,"fees":0.0,"slippage":0.0,"execution_cost":0.0}
    pnl=[_f(x.net_pnl) for x in rows]; wins=[x for x in pnl if x>0]; losses=[x for x in pnl if x<0]
    eq=0.0;peak=0.0;dd=0.0
    for p in pnl:eq+=p;peak=max(peak,eq);dd=max(dd,peak-eq)
    gp=sum(wins);gl=abs(sum(losses));fees=sum(_f(x.fees) for x in rows);slip=sum(_f(x.slippage) for x in rows)
    return {"sample_size":n,"expectancy":sum(pnl)/n,"win_rate":len(wins)/n,"profit_factor":gp/gl if gl else (999.0 if gp else 0.0),"max_drawdown":dd,"fees":fees,"slippage":slip,"execution_cost":fees+slip}

class MonitoringPolicyCreate(BaseModel):
    model_config=ConfigDict(extra="forbid")
    name:str; description:str|None=None; status:str="draft"; scope_type:str="global"
    symbol_scope:list[str]=[]; timeframe_scope:list[str]=[]; regime_scope:list[str]=[]; strategy_scope:list[str]=[]
    blueprint_id:UUID|None=None; variant_id:UUID|None=None; research_portfolio_id:UUID|None=None; shadow_session_id:UUID|None=None; candidate_id:UUID|None=None
    trigger_rules:dict[str,Any]=Field(default_factory=lambda:{"types":["regime_change"]}); thresholds:dict[str,Any]=Field(default_factory=dict)
    minimum_sample_size:int=Field(default_factory=lambda:_env_int("AI_MONITOR_MIN_SAMPLE_SIZE",20,1,100000))
    cooldown_seconds:int=Field(default_factory=lambda:_env_int("AI_MONITOR_DEFAULT_COOLDOWN_SECONDS",21600,0,31536000))

class MonitoringPolicyPatch(BaseModel):
    model_config=ConfigDict(extra="forbid")
    name:str|None=None; description:str|None=None; status:str|None=None; trigger_rules:dict[str,Any]|None=None; thresholds:dict[str,Any]|None=None
    minimum_sample_size:int|None=Field(default=None,ge=1); cooldown_seconds:int|None=Field(default=None,ge=0)

class MonitoringPolicyRead(BaseModel):
    id:UUID; name:str; description:str|None; policy_version:str; status:str; scope_type:str
    symbol_scope:list[Any]; timeframe_scope:list[Any]; regime_scope:list[Any]; strategy_scope:list[Any]
    blueprint_id:UUID|None; variant_id:UUID|None; research_portfolio_id:UUID|None; shadow_session_id:UUID|None; candidate_id:UUID|None
    trigger_rules:dict[str,Any]; thresholds:dict[str,Any]; minimum_sample_size:int; cooldown_seconds:int
    last_evaluated_at:datetime|None; last_triggered_at:datetime|None; configuration:dict[str,Any]; configuration_hash:str; created_at:datetime; updated_at:datetime

class TriggerRead(BaseModel):
    id:UUID; policy_id:UUID; trigger_type:str; status:str; trigger_version:str; detected_at:datetime; evidence_start:datetime|None; evidence_end:datetime|None
    symbol:str|None; timeframe:str|None; regime:str|None; strategy_name:str|None; source_entity_type:str|None; source_entity_id:UUID|None
    baseline_metrics:dict[str,Any]; current_metrics:dict[str,Any]; difference_metrics:dict[str,Any]; severity_score:Decimal; confidence_score:Decimal
    evidence_scope:dict[str,Any]; trigger_reasons:list[Any]; warnings:list[Any]; configuration:dict[str,Any]; configuration_hash:str; research_job_id:UUID|None; created_at:datetime

class JobRead(BaseModel):
    id:UUID; trigger_event_id:UUID|None; policy_id:UUID|None; job_type:str; status:str; job_version:str; requested_scope:dict[str,Any]; evidence_scope:dict[str,Any]
    target_pipeline_stage:str; requested_actions:list[Any]; configuration:dict[str,Any]; configuration_hash:str; started_at:datetime|None; completed_at:datetime|None
    result_summary:dict[str,Any]; created_entity_ids:dict[str,Any]; warnings:list[Any]; failure_reason:str|None; retry_count:int; created_at:datetime; updated_at:datetime

class ResearchMonitoringService:
    """Deterministic research monitoring only; no order/bot/risk/credential/capital authority."""
    def __init__(self,db:Session):self.db=db
    def default_thresholds(self):
        return {"expectancy_drop_fraction":.25,"drawdown_increase_fraction":.25,"win_rate_drop":.10,"profit_factor_drop_fraction":.25,"execution_cost_increase_fraction":.25,"shadow_max_drift":.35,"min_data_quality":.50,"max_overfit_risk":.70,"candidate_staleness_seconds":2592000,"portfolio_min_readiness":.50}
    def create_policy(self,req:MonitoringPolicyCreate):
        if req.status not in POLICY_STATUSES:raise ValueError("unsupported policy status")
        types=list(req.trigger_rules.get("types",[])); bad=set(types)-TRIGGER_TYPES
        if bad:raise ValueError(f"unsupported trigger types: {sorted(bad)}")
        cfg={"policy_version":POLICY_VERSION,"scope_type":req.scope_type,"symbol_scope":[x.upper() for x in req.symbol_scope],"timeframe_scope":req.timeframe_scope,"regime_scope":req.regime_scope,"strategy_scope":req.strategy_scope,"blueprint_id":str(req.blueprint_id) if req.blueprint_id else None,"variant_id":str(req.variant_id) if req.variant_id else None,"research_portfolio_id":str(req.research_portfolio_id) if req.research_portfolio_id else None,"shadow_session_id":str(req.shadow_session_id) if req.shadow_session_id else None,"candidate_id":str(req.candidate_id) if req.candidate_id else None,"trigger_rules":req.trigger_rules,"thresholds":{**self.default_thresholds(),**req.thresholds},"minimum_sample_size":req.minimum_sample_size,"cooldown_seconds":req.cooldown_seconds}
        h=canonical_hash(cfg); old=self.db.execute(select(ResearchMonitoringPolicy).where(ResearchMonitoringPolicy.policy_version==POLICY_VERSION,ResearchMonitoringPolicy.configuration_hash==h)).scalar_one_or_none()
        if old:return self._policy(old)
        row=ResearchMonitoringPolicy(name=req.name,description=req.description,policy_version=POLICY_VERSION,status=req.status,scope_type=req.scope_type,symbol_scope=cfg["symbol_scope"],timeframe_scope=req.timeframe_scope,regime_scope=req.regime_scope,strategy_scope=req.strategy_scope,blueprint_id=req.blueprint_id,variant_id=req.variant_id,research_portfolio_id=req.research_portfolio_id,shadow_session_id=req.shadow_session_id,candidate_id=req.candidate_id,trigger_rules=req.trigger_rules,thresholds=cfg["thresholds"],minimum_sample_size=req.minimum_sample_size,cooldown_seconds=req.cooldown_seconds,configuration=cfg,configuration_hash=h)
        self.db.add(row);self.db.commit();self.db.refresh(row);self._obs("ai_monitor_policy_created",{"policy_id":str(row.id),"status":row.status});return self._policy(row)
    def update_policy(self,pid:UUID,patch:MonitoringPolicyPatch):
        r=self.db.get(ResearchMonitoringPolicy,pid)
        if not r:raise LookupError("monitoring policy not found")
        data=patch.model_dump(exclude_none=True)
        if "status" in data and data["status"] not in POLICY_STATUSES:raise ValueError("unsupported policy status")
        if "trigger_rules" in data:
            bad=set(data["trigger_rules"].get("types",[]))-TRIGGER_TYPES
            if bad:raise ValueError(f"unsupported trigger types: {sorted(bad)}")
        for k,v in data.items():setattr(r,k,v)
        r.thresholds={**self.default_thresholds(),**(r.thresholds or {})}; r.configuration={**(r.configuration or {}),**data,"thresholds":r.thresholds}; r.configuration_hash=canonical_hash(r.configuration)
        self.db.commit();self.db.refresh(r);self._obs("ai_monitor_policy_updated",{"policy_id":str(r.id),"status":r.status});return self._policy(r)
    def policy(self,pid):
        r=self.db.get(ResearchMonitoringPolicy,pid);return self._policy(r) if r else None
    def policies(self,status=None,scope_type=None,symbol=None,timeframe=None,regime=None,strategy=None,limit=100,offset=0):
        q=select(ResearchMonitoringPolicy)
        if status:q=q.where(ResearchMonitoringPolicy.status==status)
        if scope_type:q=q.where(ResearchMonitoringPolicy.scope_type==scope_type)
        rows=list(self.db.execute(q.order_by(ResearchMonitoringPolicy.created_at.desc(),ResearchMonitoringPolicy.id.desc()).offset(offset).limit(limit)).scalars())
        def ok(r):return (not symbol or symbol.upper() in [str(x).upper() for x in r.symbol_scope]) and (not timeframe or timeframe in r.timeframe_scope) and (not regime or regime in r.regime_scope) and (not strategy or strategy in r.strategy_scope)
        return [self._policy(r) for r in rows if ok(r)]
    def pause(self,pid):return self.update_policy(pid,MonitoringPolicyPatch(status="paused"))
    def resume(self,pid):return self.update_policy(pid,MonitoringPolicyPatch(status="enabled"))

    def evaluate(self,pid:UUID,*,now:datetime|None=None,max_triggers:int|None=None):
        p=self.db.get(ResearchMonitoringPolicy,pid)
        if not p:raise LookupError("monitoring policy not found")
        if p.status!="enabled":raise ValueError("monitoring policy must be enabled")
        now=now or utcnow(); p.last_evaluated_at=now; results=[]
        for typ in list((p.trigger_rules or {}).get("types",[]))[:max_triggers or 100]:
            candidate=self._evaluate_type(p,typ,now)
            if candidate:
                row=self._persist_trigger(p,typ,candidate,now)
                if row:results.append(self._trigger(row))
                if max_triggers and len(results)>=max_triggers:break
        self.db.commit();return results

    def _outcomes(self,p):
        q=select(TradeOutcome)
        if p.symbol_scope:q=q.where(TradeOutcome.symbol.in_([str(x).upper() for x in p.symbol_scope]))
        if p.timeframe_scope:q=q.where(TradeOutcome.timeframe.in_(p.timeframe_scope))
        if p.strategy_scope:q=q.where(TradeOutcome.strategy_name.in_(p.strategy_scope))
        return list(self.db.execute(q.order_by(TradeOutcome.exit_time,TradeOutcome.id)).scalars())
    def _evaluate_type(self,p,typ,now):
        th={**self.default_thresholds(),**(p.thresholds or {})}
        if typ=="regime_change":
            q=select(MarketRegimeSnapshot)
            if p.symbol_scope:q=q.where(MarketRegimeSnapshot.symbol.in_([str(x).upper() for x in p.symbol_scope]))
            if p.timeframe_scope:q=q.where(MarketRegimeSnapshot.timeframe.in_(p.timeframe_scope))
            rows=list(self.db.execute(q.order_by(MarketRegimeSnapshot.candle_open_time.desc(),MarketRegimeSnapshot.id.desc()).limit(2)).scalars())
            if len(rows)<2 or rows[0].regime==rows[1].regime:return None
            return {"baseline":{"regime":rows[1].regime},"current":{"regime":rows[0].regime},"difference":{"changed":True,"previous_regime":rows[1].regime,"current_regime":rows[0].regime},"magnitude":1.0,"sample":2,"quality":_f(rows[0].confidence_score,.5),"scope":{"regime_ids":[str(x.id) for x in rows]},"source_type":"regime","source_id":rows[0].id,"symbol":rows[0].symbol,"timeframe":rows[0].timeframe,"regime":rows[0].regime,"reasons":["market_regime_changed"]}
        if typ in {"expectancy_degradation","drawdown_degradation","win_rate_degradation","profit_factor_degradation","execution_cost_drift","slippage_drift","fee_drag_increase"}:
            rows=self._outcomes(p); minimum=p.minimum_sample_size
            if len(rows)<minimum*2:return None
            baseline=_serialize_metrics(rows[:-minimum]);current=_serialize_metrics(rows[-minimum:]);key_map={"expectancy_degradation":"expectancy","drawdown_degradation":"max_drawdown","win_rate_degradation":"win_rate","profit_factor_degradation":"profit_factor","execution_cost_drift":"execution_cost","slippage_drift":"slippage","fee_drag_increase":"fees"};key=key_map[typ];b=_f(baseline[key]);c=_f(current[key]);
            if typ in {"drawdown_degradation","execution_cost_drift","slippage_drift","fee_drag_increase"}: mag=max(0,(c-b)/max(abs(b),1e-9)); threshold=th["drawdown_increase_fraction"] if typ=="drawdown_degradation" else th["execution_cost_increase_fraction"]
            elif typ=="win_rate_degradation":mag=max(0,b-c);threshold=th["win_rate_drop"]
            elif typ=="profit_factor_degradation":mag=max(0,(b-c)/max(abs(b),1e-9));threshold=th["profit_factor_drop_fraction"]
            else:mag=max(0,(b-c)/max(abs(b),1.0));threshold=th["expectancy_drop_fraction"]
            if mag<threshold:return None
            return {"baseline":baseline,"current":current,"difference":{key:c-b,"degradation_magnitude":mag},"magnitude":min(1,mag),"sample":minimum,"quality":1.0,"scope":{"outcome_ids":[str(x.id) for x in rows[-minimum:]],"baseline_outcome_ids":[str(x.id) for x in rows[:-minimum]]},"source_type":"trade_outcome","source_id":rows[-1].id,"symbol":rows[-1].symbol,"timeframe":rows[-1].timeframe,"strategy":rows[-1].strategy_name,"reasons":[typ]}
        if typ in {"shadow_performance_drift","signal_frequency_drift"}:
            s=self.db.get(ShadowResearchSession,p.shadow_session_id) if p.shadow_session_id else self.db.execute(select(ShadowResearchSession).order_by(ShadowResearchSession.updated_at.desc()).limit(1)).scalar_one_or_none()
            if not s:return None
            drift=_f((s.drift_metrics or {}).get("drift_score")); mag=drift if typ=="shadow_performance_drift" else abs(_f((s.drift_metrics or {}).get("signal_frequency_drift")))
            if mag<th["shadow_max_drift"]:return None
            return {"baseline":s.expected_metrics,"current":s.observed_metrics,"difference":s.drift_metrics,"magnitude":min(1,mag),"sample":s.simulated_trade_count,"quality":_f((s.configuration or {}).get("historical_data_quality"),.5),"scope":{"shadow_session_id":str(s.id)},"source_type":"shadow_session","source_id":s.id,"symbol":str(s.symbol_scope[0]) if s.symbol_scope else None,"timeframe":str(s.timeframe_scope[0]) if s.timeframe_scope else None,"reasons":[typ]}
        if typ in {"strategy_stability_degradation","data_quality_degradation","overfit_risk_increase"}:
            q=select(BlueprintValidationRun).where(BlueprintValidationRun.status=="completed")
            if p.blueprint_id:q=q.where(BlueprintValidationRun.blueprint_id==p.blueprint_id)
            vals=list(self.db.execute(q.order_by(BlueprintValidationRun.created_at.desc(),BlueprintValidationRun.id.desc()).limit(2)).scalars())
            if not vals:return None
            cur=vals[0]; base=vals[1] if len(vals)>1 else cur
            if typ=="strategy_stability_degradation":mag=max(0,_f(base.stability_score)-_f(cur.stability_score));threshold=.15
            elif typ=="data_quality_degradation":mag=max(0,th["min_data_quality"]-_f(cur.data_quality_score));threshold=.01
            else:mag=max(0,_f(cur.overfit_risk_score)-th["max_overfit_risk"]);threshold=.01
            if mag<threshold:return None
            return {"baseline":{"stability":_f(base.stability_score),"data_quality":_f(base.data_quality_score),"overfit_risk":_f(base.overfit_risk_score)},"current":{"stability":_f(cur.stability_score),"data_quality":_f(cur.data_quality_score),"overfit_risk":_f(cur.overfit_risk_score)},"difference":{"magnitude":mag},"magnitude":min(1,mag),"sample":cur.simulated_trade_count,"quality":_f(cur.data_quality_score),"scope":{"validation_ids":[str(x.id) for x in vals]},"source_type":"blueprint_validation","source_id":cur.id,"reasons":[typ]}
        if typ=="candidate_staleness":
            c=self.db.get(ResearchCandidateStrategy,p.candidate_id) if p.candidate_id else None
            if not c:return None
            age=max(0,(now-_aware(c.updated_at)).total_seconds()); threshold=_f(th["candidate_staleness_seconds"],2592000)
            if age<threshold:return None
            promo=self.db.execute(select(CandidatePromotionEvaluation).where(CandidatePromotionEvaluation.candidate_id==c.id).order_by(CandidatePromotionEvaluation.evaluated_at.desc()).limit(1)).scalar_one_or_none()
            return {"baseline":{"max_age_seconds":threshold},"current":{"age_seconds":age,"candidate_status":c.status},"difference":{"staleness_seconds":age-threshold},"magnitude":min(1,age/max(threshold,1)-1),"sample":1,"quality":_f(promo.data_quality_gate_passed if promo else .5),"scope":{"candidate_id":str(c.id)},"source_type":"candidate","source_id":c.id,"strategy":c.base_strategy_name,"reasons":["candidate_staleness"]}
        if typ=="research_portfolio_degradation":
            r=self.db.get(ResearchStrategyPortfolio,p.research_portfolio_id) if p.research_portfolio_id else None
            if not r:return None
            readiness=_f(r.readiness_score); mag=max(0,th["portfolio_min_readiness"]-readiness)
            if mag<=0:return None
            return {"baseline":{"minimum_readiness":th["portfolio_min_readiness"]},"current":{"readiness":readiness,"robustness":_f(r.robustness_score),"data_quality":_f(r.data_quality_score)},"difference":{"readiness_shortfall":mag},"magnitude":min(1,mag),"sample":r.component_count,"quality":_f(r.data_quality_score),"scope":{"portfolio_id":str(r.id)},"source_type":"research_portfolio","source_id":r.id,"reasons":[typ]}
        return None

    def _persist_trigger(self,p,typ,c,now):
        sample=max(0,int(c.get("sample",0))); sample_factor=min(1,sample/max(1,p.minimum_sample_size)); quality=max(0,min(1,_f(c.get("quality"),.5))); magnitude=max(0,min(1,_f(c.get("magnitude"))))
        severity=max(0,min(1,.55*magnitude+.25*sample_factor+.20*quality)); confidence=max(0,min(1,.50*sample_factor+.30*quality+.20*(1 if c.get("scope") else 0)))
        warnings=[]
        if sample<p.minimum_sample_size:warnings.append("insufficient_sample")
        scope=c.get("scope",{}); cfg={"trigger_version":TRIGGER_VERSION,"policy_id":str(p.id),"trigger_type":typ,"evidence_scope":scope,"baseline":c.get("baseline",{}),"current":c.get("current",{}),"thresholds":p.thresholds}
        h=canonical_hash(cfg); existing=self.db.execute(select(ResearchTriggerEvent).where(ResearchTriggerEvent.policy_id==p.id,ResearchTriggerEvent.trigger_version==TRIGGER_VERSION,ResearchTriggerEvent.configuration_hash==h)).scalar_one_or_none()
        if existing:return None
        cooldown=bool(p.last_triggered_at and (now-_aware(p.last_triggered_at)).total_seconds()<p.cooldown_seconds)
        status="suppressed" if cooldown or sample<p.minimum_sample_size else "detected"
        row=ResearchTriggerEvent(policy_id=p.id,trigger_type=typ,status=status,trigger_version=TRIGGER_VERSION,detected_at=now,evidence_start=None,evidence_end=now,symbol=c.get("symbol"),timeframe=c.get("timeframe"),regime=c.get("regime"),strategy_name=c.get("strategy"),source_entity_type=c.get("source_type"),source_entity_id=c.get("source_id"),baseline_metrics=c.get("baseline",{}),current_metrics=c.get("current",{}),difference_metrics=c.get("difference",{}),severity_score=D(str(severity)),confidence_score=D(str(confidence)),evidence_scope=scope,trigger_reasons=c.get("reasons",[]),warnings=warnings+(["policy_cooldown"] if cooldown else []),configuration=cfg,configuration_hash=h)
        self.db.add(row);self.db.flush()
        if status=="detected":p.last_triggered_at=now
        self.db.commit();self.db.refresh(row);self._obs("ai_monitor_trigger_suppressed" if status=="suppressed" else "ai_monitor_trigger_detected",{"trigger_id":str(row.id),"policy_id":str(p.id),"trigger_type":typ,"severity":severity,"confidence":confidence,"status":status})
        if status=="detected" and _env_bool("AI_MONITOR_AUTO_QUEUE_RESEARCH",False): self.queue_research(row.id)
        return row

    def triggers(self,policy=None,trigger_type=None,status=None,symbol=None,timeframe=None,regime=None,strategy=None,minimum_severity=None,start=None,end=None,limit=100,offset=0):
        q=select(ResearchTriggerEvent)
        for col,val in [(ResearchTriggerEvent.policy_id,policy),(ResearchTriggerEvent.trigger_type,trigger_type),(ResearchTriggerEvent.status,status),(ResearchTriggerEvent.symbol,symbol.upper() if symbol else None),(ResearchTriggerEvent.timeframe,timeframe),(ResearchTriggerEvent.regime,regime),(ResearchTriggerEvent.strategy_name,strategy)]:
            if val is not None:q=q.where(col==val)
        if minimum_severity is not None:q=q.where(ResearchTriggerEvent.severity_score>=minimum_severity)
        if start:q=q.where(ResearchTriggerEvent.detected_at>=start)
        if end:q=q.where(ResearchTriggerEvent.detected_at<=end)
        return [self._trigger(r) for r in self.db.execute(q.order_by(ResearchTriggerEvent.detected_at.desc(),ResearchTriggerEvent.id.desc()).offset(offset).limit(limit)).scalars()]
    def trigger(self,id):
        r=self.db.get(ResearchTriggerEvent,id);return self._trigger(r) if r else None
    def acknowledge(self,id):
        r=self.db.get(ResearchTriggerEvent,id)
        if not r:raise LookupError("research trigger not found")
        r.status="acknowledged";self.db.commit();self.db.refresh(r);self._obs("ai_monitor_trigger_acknowledged",{"trigger_id":str(r.id)});return self._trigger(r)

    def _job_type(self,t):
        return {"regime_change":"regime_matching_refresh","expectancy_degradation":"rerun_ai_research","drawdown_degradation":"strategy_evolution_review","win_rate_degradation":"rerun_ai_research","profit_factor_degradation":"rerun_ai_research","execution_cost_drift":"strategy_evolution_review","slippage_drift":"strategy_evolution_review","fee_drag_increase":"strategy_evolution_review","signal_frequency_drift":"shadow_readiness_review","shadow_performance_drift":"shadow_readiness_review","strategy_stability_degradation":"blueprint_revalidation","data_quality_degradation":"blueprint_review","overfit_risk_increase":"strategy_evolution_review","candidate_staleness":"candidate_readiness_review","research_portfolio_degradation":"portfolio_rebuild_review"}.get(t,"rerun_ai_research")
    def queue_research(self,trigger_id:UUID,job_type:str|None=None):
        t=self.db.get(ResearchTriggerEvent,trigger_id)
        if not t:raise LookupError("research trigger not found")
        if t.status not in {"detected","queued","failed"}:raise ValueError("trigger is not queueable")
        jt=job_type or self._job_type(t.trigger_type)
        if jt not in JOB_TYPES:raise ValueError("unsupported research job type")
        cfg={"job_version":JOB_VERSION,"trigger_id":str(t.id),"policy_id":str(t.policy_id),"job_type":jt,"evidence_scope":t.evidence_scope,"source_entity_type":t.source_entity_type,"source_entity_id":str(t.source_entity_id) if t.source_entity_id else None}
        h=canonical_hash(cfg); old=self.db.execute(select(AdaptiveResearchJob).where(AdaptiveResearchJob.job_version==JOB_VERSION,AdaptiveResearchJob.configuration_hash==h)).scalar_one_or_none()
        if old:return self._job(old)
        row=AdaptiveResearchJob(trigger_event_id=t.id,policy_id=t.policy_id,job_type=jt,status="queued",job_version=JOB_VERSION,requested_scope={"symbol":t.symbol,"timeframe":t.timeframe,"regime":t.regime,"strategy":t.strategy_name,"source_entity_type":t.source_entity_type,"source_entity_id":str(t.source_entity_id) if t.source_entity_id else None},evidence_scope=t.evidence_scope,target_pipeline_stage=jt,requested_actions=[jt],configuration=cfg,configuration_hash=h,result_summary={},created_entity_ids={},warnings=[],retry_count=0)
        self.db.add(row);self.db.flush();t.research_job_id=row.id;t.status="queued";self.db.commit();self.db.refresh(row);self._obs("ai_adaptive_research_job_queued",{"job_id":str(row.id),"trigger_id":str(t.id),"job_type":jt});return self._job(row)
    def jobs(self,status=None,job_type=None,limit=100,offset=0):
        q=select(AdaptiveResearchJob)
        if status:q=q.where(AdaptiveResearchJob.status==status)
        if job_type:q=q.where(AdaptiveResearchJob.job_type==job_type)
        return [self._job(r) for r in self.db.execute(q.order_by(AdaptiveResearchJob.created_at.desc(),AdaptiveResearchJob.id.desc()).offset(offset).limit(limit)).scalars()]
    def job(self,id):
        r=self.db.get(AdaptiveResearchJob,id);return self._job(r) if r else None
    def cancel_job(self,id):
        r=self.db.get(AdaptiveResearchJob,id)
        if not r:raise LookupError("adaptive research job not found")
        if r.status not in {"queued","failed"}:raise ValueError("only queued/failed research jobs can be cancelled")
        r.status="cancelled";r.completed_at=utcnow();self.db.commit();self.db.refresh(r);return self._job(r)
    def process_job(self,id):
        r=self.db.get(AdaptiveResearchJob,id)
        if not r:raise LookupError("adaptive research job not found")
        if r.status not in {"queued","failed"}:return self._job(r)
        max_retries=_env_int("AI_MONITOR_MAX_JOB_RETRIES",1,0,10)
        if r.retry_count>max_retries: return self._job(r)
        r.status="running";r.started_at=utcnow();self.db.commit();self._obs("ai_adaptive_research_job_started",{"job_id":str(r.id),"job_type":r.job_type})
        try:
            summary,created=self._dispatch(r);r.result_summary=summary;r.created_entity_ids=created;r.status="completed";r.completed_at=utcnow();r.failure_reason=None;self.db.commit();self._obs("ai_adaptive_research_job_completed",{"job_id":str(r.id),"job_type":r.job_type});return self._job(r)
        except Exception as exc:
            self.db.rollback();r=self.db.get(AdaptiveResearchJob,id);r.retry_count+=1;r.status="failed";r.failure_reason=f"research_job_error:{type(exc).__name__}";r.completed_at=utcnow();self.db.commit();self._obs("ai_adaptive_research_job_failed",{"job_id":str(r.id),"job_type":r.job_type,"retry_count":r.retry_count});return self._job(r)
    def _dispatch(self,j):
        scope=j.requested_scope or {}; sid=scope.get("source_entity_id")
        if j.job_type=="rerun_ai_research":
            from .orchestrator import AIResearchOrchestrator
            from .schemas import ResearchRunRequest
            out=AIResearchOrchestrator(self.db).run(ResearchRunRequest(run_type="performance_review",symbol=scope.get("symbol"),timeframe=scope.get("timeframe"),regime=scope.get("regime"),strategy=scope.get("strategy")))
            return {"status":out.status},{"ai_research_run_id":str(out.id)}
        if j.job_type=="regenerate_hypotheses":
            from packages.research.hypotheses import ResearchHypothesisService, HypothesisGenerateRequest
            rows=ResearchHypothesisService(self.db).generate(HypothesisGenerateRequest(symbol=scope.get("symbol"),timeframe=scope.get("timeframe"),strategy=scope.get("strategy")))
            return {"hypotheses_generated":len(rows)},{"hypothesis_ids":[str(x.id) for x in rows]}
        if j.job_type=="blueprint_revalidation" and sid:
            from .validation import BlueprintValidationService, BlueprintValidationRequest
            source=self.db.get(BlueprintValidationRun,UUID(sid))
            if not source:raise ValueError("validation source unavailable")
            out=BlueprintValidationService(self.db).validate(source.blueprint_id,BlueprintValidationRequest(validation_type="historical_backtest"))
            return {"passed":out.passed},{"validation_id":str(out.id)}
        if j.job_type=="strategy_evolution_review" and sid:
            from .evolution import StrategyEvolutionService, EvolutionRunRequest
            source=self.db.get(BlueprintValidationRun,UUID(sid))
            if not source:raise ValueError("validation source unavailable")
            out=StrategyEvolutionService(self.db).create_run(EvolutionRunRequest(source_blueprint_id=source.blueprint_id,source_validation_id=source.id,requested_variants=3,allow_failed_source=not source.passed))
            return {"status":out.status},{"evolution_run_id":str(out.id)}
        if j.job_type=="regime_matching_refresh":
            from .matching import StrategyMatchingService, ProfileGenerateRequest
            if not scope.get("regime"): raise ValueError("regime scope required for matching refresh")
            # Refresh only when a concrete blueprint/variant source is present; otherwise record bounded review.
            if scope.get("source_entity_type")=="blueprint_validation" and sid:
                source=self.db.get(BlueprintValidationRun,UUID(sid))
                out=StrategyMatchingService(self.db).generate_profile(ProfileGenerateRequest(regime=scope.get("regime"),symbol=scope.get("symbol"),timeframe=scope.get("timeframe"),blueprint_id=source.blueprint_id))
                return {"compatibility_score":float(out.compatibility_score)},{"strategy_regime_profile_id":str(out.id)}
            return {"status":"matching_refresh_reviewed","regime":scope.get("regime")},{}
        if j.job_type=="portfolio_rebuild_review":
            from .matching import StrategyMatchingService
            return {"status":"portfolio_rebuild_reviewed","available_portfolios":len(StrategyMatchingService(self.db).portfolios(limit=20,offset=0))},{}
        if j.job_type=="shadow_readiness_review" and sid:
            from .shadow import ShadowResearchService
            out=ShadowResearchService(self.db).readiness(UUID(sid));return out,{"shadow_session_id":sid}
        if j.job_type=="candidate_readiness_review" and sid:
            c=self.db.get(ResearchCandidateStrategy,UUID(sid))
            if not c:raise ValueError("candidate unavailable")
            p=self.db.execute(select(CandidatePromotionEvaluation).where(CandidatePromotionEvaluation.candidate_id==c.id).order_by(CandidatePromotionEvaluation.evaluated_at.desc()).limit(1)).scalar_one_or_none()
            return {"candidate_status":c.status,"promotion_evaluation_exists":bool(p),"promotion_passed":bool(p and p.overall_passed)},{"candidate_id":sid}
        return {"status":"review_recorded","message":"bounded research review requires explicit source-specific follow-up"},{}

    def monitor_status(self):
        enabled=self.db.execute(select(func.count()).select_from(ResearchMonitoringPolicy).where(ResearchMonitoringPolicy.status=="enabled")).scalar_one()
        recent=self.db.execute(select(func.count()).select_from(ResearchTriggerEvent).where(ResearchTriggerEvent.detected_at>=utcnow()-timedelta(days=1))).scalar_one()
        active=self.db.execute(select(func.count()).select_from(AdaptiveResearchJob).where(AdaptiveResearchJob.status.in_(["queued","running"]))).scalar_one()
        failed=self.db.execute(select(func.count()).select_from(AdaptiveResearchJob).where(AdaptiveResearchJob.status=="failed")).scalar_one()
        worker=self.db.execute(select(ResearchMonitorWorkerStatus).order_by(ResearchMonitorWorkerStatus.last_heartbeat.desc()).limit(1)).scalar_one_or_none()
        last_eval=self.db.execute(select(func.max(ResearchMonitoringPolicy.last_evaluated_at))).scalar_one()
        return {"enabled_policy_count":enabled,"recent_trigger_count":recent,"active_research_job_count":active,"failed_job_count":failed,"worker_heartbeat":worker.last_heartbeat if worker else None,"worker_name":worker.worker_name if worker else None,"last_policy_evaluation":last_eval,"auto_queue_research":_env_bool("AI_MONITOR_AUTO_QUEUE_RESEARCH",False),"postgresql_authoritative":True,"valkey_role":"transient_coordination_only","research_only":True,"trading_activation":False}

    def worker_cycle(self,worker_name="research-monitor-worker"):
        now=utcnow(); status=self.db.get(ResearchMonitorWorkerStatus,worker_name)
        if not status:status=ResearchMonitorWorkerStatus(worker_name=worker_name,last_heartbeat=now,policies_evaluated=0,triggers_detected=0,jobs_processed=0,jobs_failed=0);self.db.add(status)
        status.last_heartbeat=now;status.last_cycle_started=now;status.last_error=None;self.db.commit()
        pe=td=jp=jf=0
        try:
            maxp=_env_int("AI_MONITOR_MAX_POLICIES_PER_CYCLE",50,1,500);maxt=_env_int("AI_MONITOR_MAX_TRIGGERS_PER_CYCLE",20,1,500);maxj=_env_int("AI_MONITOR_MAX_JOBS_PER_CYCLE",10,0,100)
            policies=list(self.db.execute(select(ResearchMonitoringPolicy).where(ResearchMonitoringPolicy.status=="enabled").order_by(ResearchMonitoringPolicy.updated_at,ResearchMonitoringPolicy.id).limit(maxp)).scalars())
            for p in policies:
                if td>=maxt:break
                rows=self.evaluate(p.id,max_triggers=maxt-td);pe+=1;td+=sum(1 for x in rows if x.status=="detected")
            jobs=list(self.db.execute(select(AdaptiveResearchJob).where(AdaptiveResearchJob.status.in_(["queued","failed"])).order_by(AdaptiveResearchJob.created_at,AdaptiveResearchJob.id).limit(maxj)).scalars())
            for j in jobs:
                out=self.process_job(j.id);jp+=1;jf+=1 if out.status=="failed" else 0
        except Exception as exc:
            self.db.rollback();status=self.db.get(ResearchMonitorWorkerStatus,worker_name);status.last_error=f"monitor_cycle_error:{type(exc).__name__}";self.db.commit()
        status=self.db.get(ResearchMonitorWorkerStatus,worker_name);status.last_heartbeat=utcnow();status.last_cycle_completed=utcnow();status.policies_evaluated=pe;status.triggers_detected=td;status.jobs_processed=jp;status.jobs_failed=jf;self.db.commit();return {"worker_name":worker_name,"policies_evaluated":pe,"triggers_detected":td,"jobs_processed":jp,"jobs_failed":jf,"last_error":status.last_error}

    def _obs(self,event,ctx):observe_best_effort(self.db,ObservationCreate(event_type=event,source="ai_research_monitor",context=ctx))
    @staticmethod
    def _policy(r):return MonitoringPolicyRead.model_validate({k:getattr(r,k) for k in MonitoringPolicyRead.model_fields})
    @staticmethod
    def _trigger(r):return TriggerRead.model_validate({k:getattr(r,k) for k in TriggerRead.model_fields})
    @staticmethod
    def _job(r):return JobRead.model_validate({k:getattr(r,k) for k in JobRead.model_fields})
