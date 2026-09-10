from __future__ import annotations

import hashlib, json, os, uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import (
    AIStrategyBlueprint, AIStrategyVariant, BlueprintValidationRun, BlueprintSimulatedTrade,
    ResearchStrategyPortfolio, StrategyRegimeProfile, ShadowResearchSession, ShadowResearchTrade,
    ResearchCandidateHandoff, ResearchCandidateStrategy, ResearchHypothesis, ResearchExperiment,
    ResearchObservation,
)
from packages.research.ai.validation import BlueprintValidationService, BlueprintValidationRequest
from packages.research.candidates import ResearchCandidateService, CandidateCreateRequest

SESSION_VERSION = "1.0.0"
HANDOFF_VERSION = "1.0.0"
D = Decimal


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

def _f(v):
    try:return float(v or 0)
    except (TypeError,ValueError):return 0.0

def _env_float(name, default, lo=None, hi=None):
    try:v=float(os.getenv(name,str(default)))
    except ValueError:v=float(default)
    if lo is not None:v=max(lo,v)
    if hi is not None:v=min(hi,v)
    return v

def _env_int(name, default, lo=1, hi=100000):
    try:v=int(os.getenv(name,str(default)))
    except ValueError:v=default
    return max(lo,min(hi,v))

def _env_bool(name, default=False):
    return os.getenv(name,"true" if default else "false").strip().lower() in {"1","true","yes","on"}

class ShadowSessionCreateRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    source_type:str=Field(pattern="^(blueprint|variant|portfolio)$")
    blueprint_id:uuid.UUID|None=None
    variant_id:uuid.UUID|None=None
    research_portfolio_id:uuid.UUID|None=None
    exchange:str="binance"

class HandoffCreateRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    source_type:str=Field(pattern="^(blueprint|variant|champion)$")
    validation_id:uuid.UUID
    variant_id:uuid.UUID|None=None
    shadow_session_id:uuid.UUID|None=None
    research_portfolio_id:uuid.UUID|None=None

class ShadowSessionRead(BaseModel):
    id:uuid.UUID; source_type:str; blueprint_id:uuid.UUID|None; variant_id:uuid.UUID|None; research_portfolio_id:uuid.UUID|None
    session_version:str; status:str; exchange:str; symbol_scope:list[Any]; timeframe_scope:list[Any]; regime_scope:list[Any]
    configuration:dict[str,Any]; configuration_hash:str; execution_convention:str; fee_bps:Decimal; slippage_bps:Decimal
    started_at:datetime; stopped_at:datetime|None; last_processed_candle_time:datetime|None
    observed_candle_count:int; signal_count:int; simulated_trade_count:int; expected_metrics:dict[str,Any]; observed_metrics:dict[str,Any]
    drift_metrics:dict[str,Any]; readiness_score:Decimal; warnings:list[Any]; blocking_reasons:list[Any]; created_at:datetime; updated_at:datetime

class ShadowTradeRead(BaseModel):
    id:uuid.UUID; session_id:uuid.UUID; blueprint_id:uuid.UUID|None; variant_id:uuid.UUID|None; symbol:str; timeframe:str; side:str
    signal_time:datetime; entry_time:datetime; exit_time:datetime|None; entry_price:Decimal; exit_price:Decimal|None; quantity:Decimal
    gross_pnl:Decimal; net_pnl:Decimal; return_pct:Decimal; simulated_fees:Decimal; simulated_slippage:Decimal; mae:Decimal; mfe:Decimal
    holding_time_seconds:int; entry_regime:str|None; exit_regime:str|None; exit_reason:str|None; parameter_set_hash:str; context:dict[str,Any]; created_at:datetime

class HandoffRead(BaseModel):
    id:uuid.UUID; source_type:str; blueprint_id:uuid.UUID|None; variant_id:uuid.UUID|None; validation_id:uuid.UUID
    shadow_session_id:uuid.UUID|None; research_portfolio_id:uuid.UUID|None; handoff_version:str; status:str
    strategy_definition:dict[str,Any]; parameter_values:dict[str,Any]; symbol_scope:list[Any]; timeframe_scope:list[Any]; regime_scope:list[Any]
    validation_summary:dict[str,Any]; shadow_summary:dict[str,Any]; regime_summary:dict[str,Any]; portfolio_summary:dict[str,Any]
    risk_constraints:dict[str,Any]; protection_requirements:dict[str,Any]; readiness_score:Decimal; warnings:list[Any]; blocking_reasons:list[Any]
    configuration:dict[str,Any]; configuration_hash:str; created_candidate_id:uuid.UUID|None; created_at:datetime; updated_at:datetime

class ShadowResearchService:
    """Research-only shadow simulator and controlled Phase-3 candidate handoff."""
    def __init__(self,db:Session): self.db=db; self.validator=BlueprintValidationService(db)

    def _latest_validation(self, blueprint_id, variant_id=None):
        rows=self.db.execute(select(BlueprintValidationRun).where(BlueprintValidationRun.blueprint_id==blueprint_id,BlueprintValidationRun.status=="completed").order_by(BlueprintValidationRun.created_at.desc(),BlueprintValidationRun.id.desc())).scalars().all()
        if variant_id:
            rows=[r for r in rows if str((r.configuration or {}).get("source_variant_id",""))==str(variant_id)]
        return rows[0] if rows else None

    def _source(self, req:ShadowSessionCreateRequest):
        if req.source_type=="blueprint":
            if not req.blueprint_id: raise ValueError("blueprint_id is required")
            bp=self.db.get(AIStrategyBlueprint,req.blueprint_id)
            if not bp or bp.status!="accepted_for_validation": raise ValueError("accepted blueprint source required")
            val=self._latest_validation(bp.id)
            if not val or not val.passed: raise ValueError("passing completed blueprint validation required")
            return bp,None,val
        if req.source_type=="variant":
            if not req.variant_id:raise ValueError("variant_id is required")
            v=self.db.get(AIStrategyVariant,req.variant_id)
            if not v or v.status not in {"validated","challenger","champion"}:raise ValueError("validated variant source required")
            bp=self.db.get(AIStrategyBlueprint,v.source_blueprint_id); val=self._latest_validation(bp.id,v.id)
            if not val or not val.passed: raise ValueError("passing variant validation required")
            return bp,v,val
        if not req.research_portfolio_id:raise ValueError("research_portfolio_id is required")
        p=self.db.get(ResearchStrategyPortfolio,req.research_portfolio_id)
        if not p or p.status not in {"evaluated","review_required","accepted_for_research"}:raise ValueError("evaluated research portfolio required")
        if p.source_variant_ids:
            v=self.db.get(AIStrategyVariant,uuid.UUID(str(p.source_variant_ids[0]))); bp=self.db.get(AIStrategyBlueprint,v.source_blueprint_id); val=self._latest_validation(bp.id,v.id); return bp,v,val
        if p.source_blueprint_ids:
            bp=self.db.get(AIStrategyBlueprint,uuid.UUID(str(p.source_blueprint_ids[0]))); return bp,None,self._latest_validation(bp.id)
        raise ValueError("portfolio has no validated strategy component")

    def create_session(self,req:ShadowSessionCreateRequest):
        bp,v,val=self._source(req)
        cfg={"session_version":SESSION_VERSION,"source_type":req.source_type,"blueprint_id":str(bp.id),"variant_id":str(v.id) if v else None,"portfolio_id":str(req.research_portfolio_id) if req.research_portfolio_id else None,"validation_id":str(val.id),"exchange":req.exchange,"execution_convention":val.configuration.get("execution_convention","signal_close_next_candle_open"),"fee_bps":val.configuration.get("fee_bps",10),"slippage_bps":val.configuration.get("slippage_bps",5),"intrabar_conflict_policy":val.configuration.get("intrabar_conflict_policy","stop_first"),"max_candles_per_process":_env_int("AI_SHADOW_MAX_CANDLES_PER_PROCESS",250),"historical_data_quality":float(val.data_quality_score),"historical_overfit_risk":float(val.overfit_risk_score)}
        h=canonical_hash(cfg); existing=self.db.execute(select(ShadowResearchSession).where(ShadowResearchSession.session_version==SESSION_VERSION,ShadowResearchSession.configuration_hash==h)).scalar_one_or_none()
        if existing:return self._session(existing)
        row=ShadowResearchSession(source_type=req.source_type,blueprint_id=bp.id,variant_id=v.id if v else None,research_portfolio_id=req.research_portfolio_id,session_version=SESSION_VERSION,status="created",exchange=req.exchange,symbol_scope=v.symbol_scope if v else bp.symbol_scope,timeframe_scope=v.timeframe_scope if v else bp.timeframe_scope,regime_scope=v.regime_scope if v else bp.regime_scope,configuration=cfg,configuration_hash=h,execution_convention=cfg["execution_convention"],fee_bps=D(str(cfg["fee_bps"])),slippage_bps=D(str(cfg["slippage_bps"])),expected_metrics=val.combined_metrics or {},observed_metrics={},drift_metrics={},readiness_score=D("0"),warnings=[],blocking_reasons=[])
        self.db.add(row);self.db.commit();self.db.refresh(row);self._observe("ai_shadow_session_created",row,{"source_type":row.source_type,"validation_id":str(val.id)});return self._session(row)

    def _logic_source(self,s):
        bp=self.db.get(AIStrategyBlueprint,s.blueprint_id); v=self.db.get(AIStrategyVariant,s.variant_id) if s.variant_id else None
        if not v:return bp,{}
        proxy=SimpleNamespace(id=bp.id,entry_logic=v.entry_logic,exit_logic=v.exit_logic,protection_logic=v.protection_logic,risk_constraints=v.risk_constraints,indicator_requirements=v.indicator_requirements,regime_scope=v.regime_scope,symbol_scope=v.symbol_scope,timeframe_scope=v.timeframe_scope)
        return proxy,v.parameter_values or {}

    def process(self,session_id:uuid.UUID):
        s=self.db.get(ShadowResearchSession,session_id)
        if not s:raise LookupError("shadow session not found")
        if s.status in {"completed","archived","failed"}:raise ValueError("shadow session is not processable")
        if s.status=="paused":raise ValueError("shadow session is paused")
        bp,params=self._logic_source(s)
        req=BlueprintValidationRequest(symbol=s.symbol_scope[0] if s.symbol_scope else None,timeframe=s.timeframe_scope[0] if s.timeframe_scope else None,regime=s.regime_scope[0] if len(s.regime_scope)==1 else None,validation_fraction=0)
        records=self.validator._records(bp,req)
        start=0
        if s.last_processed_candle_time:
            for idx,(c,_,__) in enumerate(records):
                if c.open_time<=s.last_processed_candle_time:start=idx+1
        cap=int(s.configuration.get("max_candles_per_process",250)); new=records[start:start+cap]
        if not new:
            s.status="running" if s.status=="created" else s.status;self.db.commit();return self._session(s)
        context_start=max(0,start-1); scoped=records[context_start:start+len(new)]
        config={"intrabar_conflict_policy":"stop_first","fee_bps":float(s.fee_bps),"slippage_bps":float(s.slippage_bps),"fixed_notional":1000.0}
        trades,signals=self.validator._simulate(bp,scoped,params,config)
        lower=new[0][0].open_time
        created=0
        for t in trades:
            sig=datetime.fromisoformat(t["context"]["signal_time"])
            if sig<lower:continue
            exists=self.db.execute(select(ShadowResearchTrade).where(ShadowResearchTrade.session_id==s.id,ShadowResearchTrade.signal_time==sig,ShadowResearchTrade.entry_time==t["entry_time"],ShadowResearchTrade.parameter_set_hash==canonical_hash(params))).scalar_one_or_none()
            if exists:continue
            self.db.add(ShadowResearchTrade(session_id=s.id,blueprint_id=s.blueprint_id,variant_id=s.variant_id,symbol=t["symbol"],timeframe=t["timeframe"],side=t["side"],signal_time=sig,entry_time=t["entry_time"],exit_time=t["exit_time"],entry_price=t["entry_price"],exit_price=t["exit_price"],quantity=t["quantity"],gross_pnl=t["gross_pnl"],net_pnl=t["net_pnl"],return_pct=t["return_pct"],simulated_fees=t["simulated_fees"],simulated_slippage=t["simulated_slippage"],mae=t["mae"],mfe=t["mfe"],holding_time_seconds=t["holding_time_seconds"],entry_regime=t["entry_regime"],exit_regime=t["exit_regime"],exit_reason=t["exit_reason"],parameter_set_hash=canonical_hash(params),context=t["context"]));created+=1
        s.status="running";s.last_processed_candle_time=new[-1][0].open_time;s.observed_candle_count+=len(new);s.signal_count+=sum(1 for t in trades if datetime.fromisoformat(t["context"]["signal_time"])>=lower)
        self.db.flush(); rows=self.db.execute(select(ShadowResearchTrade).where(ShadowResearchTrade.session_id==s.id).order_by(ShadowResearchTrade.entry_time)).scalars().all(); s.simulated_trade_count=len(rows)
        metrics=self._metrics(rows);s.observed_metrics=metrics;s.drift_metrics=self._drift(s.expected_metrics,metrics,s.observed_candle_count);s.readiness_score=D(str(self._readiness(s,metrics)));s.blocking_reasons=self._shadow_failures(s,metrics);s.warnings=["small_shadow_sample"] if len(rows)<_env_int("AI_SHADOW_MIN_TRADES",10) else []
        self.db.commit();self.db.refresh(s);self._observe("ai_shadow_session_processed",s,{"processed_candles":len(new),"new_trades":created,"drift_score":s.drift_metrics.get("drift_score")});self._observe("ai_shadow_drift_evaluated",s,{"drift":s.drift_metrics,"readiness_score":str(s.readiness_score)});return self._session(s)

    def _metrics(self,rows):
        trades=[{"net_pnl":r.net_pnl,"gross_pnl":r.gross_pnl,"return_pct":r.return_pct,"simulated_fees":r.simulated_fees,"simulated_slippage":r.simulated_slippage,"mae":r.mae,"mfe":r.mfe,"holding_time_seconds":r.holding_time_seconds,"entry_regime":r.entry_regime} for r in rows]
        return self.validator.metrics(trades)
    def _drift(self,expected,observed,candles):
        keys=[("expectancy",10.0),("win_rate",1.0),("profit_factor",2.0),("max_drawdown",100.0),("average_holding_time",3600.0)]
        diffs={k:abs(_f(observed.get(k))-_f(expected.get(k)))/max(scale,abs(_f(expected.get(k))),1e-9) for k,scale in keys}
        ec=_f(observed.get("fees_total"))+_f(observed.get("slippage_total")); ee=_f(expected.get("fees_total"))+_f(expected.get("slippage_total")); diffs["execution_cost_drift"]=abs(ec-ee)/max(1,abs(ee))
        raw=sum(min(1,v) for v in diffs.values())/len(diffs); sample=min(1,_f(observed.get("trade_count"))/_env_int("AI_SHADOW_MIN_TRADES",10)); score=max(0,min(1,raw*sample))
        return {**{k:round(v,6) for k,v in diffs.items()},"drift_score":round(score,6),"sample_factor":round(sample,6)}
    def _readiness(self,s,m):
        sample=min(1,_f(m.get("trade_count"))/_env_int("AI_SHADOW_MIN_TRADES",10)); exp=0.5+0.5*max(-1,min(1,_f(m.get("expectancy"))/10)); drift=1-_f(s.drift_metrics.get("drift_score")); expected_quality=_f(s.expected_metrics.get("data_quality_score",s.configuration.get("data_quality_score",0.7))) or 0.7
        return round(max(0,min(1,.25*sample+.25*exp+.25*drift+.25*expected_quality)),6)
    def _shadow_failures(self,s,m):
        f=[];g={"min_trades":_env_int("AI_SHADOW_MIN_TRADES",10),"min_expectancy":_env_float("AI_SHADOW_MIN_EXPECTANCY",0),"max_drawdown":_env_float("AI_SHADOW_MAX_DRAWDOWN",1000),"max_drift":_env_float("AI_SHADOW_MAX_DRIFT",.5,0,1),"min_data_quality":_env_float("AI_SHADOW_MIN_DATA_QUALITY",.6,0,1),"min_readiness":_env_float("AI_SHADOW_MIN_READINESS_SCORE",.6,0,1)};s.configuration={**s.configuration,"shadow_gates":g}
        if _f(m.get("trade_count"))<g["min_trades"]:f.append("minimum_shadow_trades")
        if _f(m.get("expectancy"))<g["min_expectancy"]:f.append("minimum_shadow_expectancy")
        if _f(m.get("max_drawdown"))>g["max_drawdown"]:f.append("maximum_shadow_drawdown")
        if _f(s.drift_metrics.get("drift_score"))>g["max_drift"]:f.append("maximum_shadow_drift")
        if _f(s.configuration.get("historical_data_quality"))<g["min_data_quality"]:f.append("minimum_shadow_data_quality")
        if _f(s.readiness_score)<g["min_readiness"]:f.append("minimum_shadow_readiness")
        return f

    def pause(self,id):return self._status(id,"paused")
    def resume(self,id):return self._status(id,"running")
    def complete(self,id):
        out=self._status(id,"completed");self._observe("ai_shadow_session_completed",self.db.get(ShadowResearchSession,id),{"readiness_score":str(out.readiness_score)});return out
    def _status(self,id,status):
        s=self.db.get(ShadowResearchSession,id)
        if not s:raise LookupError("shadow session not found")
        if status=="running" and s.status!="paused":raise ValueError("only paused sessions can resume")
        if status=="paused" and s.status!="running":raise ValueError("only running sessions can pause")
        if status=="completed" and s.status not in {"running","paused"}:raise ValueError("session must run before completion")
        s.status=status;s.stopped_at=datetime.now(timezone.utc) if status=="completed" else None;self.db.commit();self.db.refresh(s);return self._session(s)
    def sessions(self,status=None,source_type=None,limit=100,offset=0):
        q=select(ShadowResearchSession)
        if status:q=q.where(ShadowResearchSession.status==status)
        if source_type:q=q.where(ShadowResearchSession.source_type==source_type)
        rows=self.db.execute(q.order_by(ShadowResearchSession.created_at.desc()).offset(offset).limit(limit)).scalars().all();return [self._session(r) for r in rows]
    def session(self,id):
        r=self.db.get(ShadowResearchSession,id);return self._session(r) if r else None
    def trades(self,id):
        return [self._trade(r) for r in self.db.execute(select(ShadowResearchTrade).where(ShadowResearchTrade.session_id==id).order_by(ShadowResearchTrade.signal_time.asc(),ShadowResearchTrade.id.asc())).scalars().all()]

    def create_handoff(self,req:HandoffCreateRequest):
        val=self.db.get(BlueprintValidationRun,req.validation_id)
        if not val:raise LookupError("validation not found")
        bp=self.db.get(AIStrategyBlueprint,val.blueprint_id)
        v=self.db.get(AIStrategyVariant,req.variant_id) if req.variant_id else None
        if req.source_type in {"variant","champion"} and not v:raise ValueError("variant source required")
        if v and v.status not in {"validated","challenger","champion"}:raise ValueError("validated variant source required")
        if req.source_type=="champion" and v.status!="champion":raise ValueError("research champion source required")
        blocking=[]
        if v and str((val.configuration or {}).get("source_variant_id",""))!=str(v.id):blocking.append("validation_does_not_match_variant")
        if not val.passed or val.status!="completed":blocking.append("passing_completed_validation_required")
        logic=v or bp; protection=logic.protection_logic or {}
        if not protection and not _f((logic.exit_logic or {}).get("stop_loss_pct")):blocking.append("mandatory_protection_required")
        if _f(val.overfit_risk_score)>_env_float("AI_VALIDATION_MAX_OVERFIT_RISK",.65,0,1):blocking.append("overfit_risk_too_high")
        if _f(val.data_quality_score)<_env_float("AI_VALIDATION_MIN_DATA_QUALITY",.6,0,1):blocking.append("data_quality_too_low")
        shadow=None
        if req.shadow_session_id:
            shadow=self.db.get(ShadowResearchSession,req.shadow_session_id)
            if not shadow:raise LookupError("shadow session not found")
            if shadow.blocking_reasons or _f(shadow.readiness_score)<_env_float("AI_SHADOW_MIN_READINESS_SCORE",.6,0,1):blocking.append("shadow_readiness_failed")
        elif _env_bool("AI_HANDOFF_REQUIRE_SHADOW",False):blocking.append("shadow_session_required")
        portfolio=self.db.get(ResearchStrategyPortfolio,req.research_portfolio_id) if req.research_portfolio_id else None
        readiness=max(0,min(1,.35*_f(val.score)+.25*_f(val.stability_score)+.25*_f(val.data_quality_score)+.15*(1-_f(val.overfit_risk_score))))
        if shadow: readiness=.75*readiness+.25*_f(shadow.readiness_score)
        cfg={"handoff_version":HANDOFF_VERSION,"source_type":req.source_type,"blueprint_id":str(bp.id),"variant_id":str(v.id) if v else None,"validation_id":str(val.id),"shadow_session_id":str(req.shadow_session_id) if req.shadow_session_id else None,"portfolio_id":str(req.research_portfolio_id) if req.research_portfolio_id else None,"validation_hash":val.configuration_hash,"source_hash":logic.configuration_hash,"require_shadow":_env_bool("AI_HANDOFF_REQUIRE_SHADOW",False)}
        h=canonical_hash(cfg);existing=self.db.execute(select(ResearchCandidateHandoff).where(ResearchCandidateHandoff.handoff_version==HANDOFF_VERSION,ResearchCandidateHandoff.configuration_hash==h)).scalar_one_or_none()
        if existing:return self._handoff(existing)
        row=ResearchCandidateHandoff(source_type=req.source_type,blueprint_id=bp.id,variant_id=v.id if v else None,validation_id=val.id,shadow_session_id=req.shadow_session_id,research_portfolio_id=req.research_portfolio_id,handoff_version=HANDOFF_VERSION,status="blocked" if blocking else "readiness_passed",strategy_definition={"entry_logic":logic.entry_logic,"exit_logic":logic.exit_logic,"protection_logic":logic.protection_logic,"feature_requirements":logic.feature_requirements,"indicator_requirements":logic.indicator_requirements},parameter_values=(v.parameter_values if v else val.parameter_set) or {},symbol_scope=logic.symbol_scope,timeframe_scope=logic.timeframe_scope,regime_scope=logic.regime_scope,validation_summary={"validation_id":str(val.id),"passed":val.passed,"score":str(val.score),"stability_score":str(val.stability_score),"data_quality_score":str(val.data_quality_score),"overfit_risk_score":str(val.overfit_risk_score),"metrics":val.combined_metrics,"execution_cost_metrics":val.execution_cost_metrics},shadow_summary={"session_id":str(shadow.id),"readiness_score":str(shadow.readiness_score),"drift":shadow.drift_metrics,"metrics":shadow.observed_metrics} if shadow else {},regime_summary={},portfolio_summary={"portfolio_id":str(portfolio.id),"readiness_score":str(portfolio.readiness_score),"status":portfolio.status} if portfolio else {},risk_constraints=logic.risk_constraints or {},protection_requirements=protection or {"stop_loss_pct":(logic.exit_logic or {}).get("stop_loss_pct")},readiness_score=D(str(round(readiness,6))),warnings=[],blocking_reasons=blocking,configuration=cfg,configuration_hash=h)
        self.db.add(row);self.db.commit();self.db.refresh(row);self._observe("ai_candidate_handoff_created",row,{"validation_id":str(val.id),"status":row.status,"readiness_score":str(row.readiness_score)});self._observe("ai_candidate_handoff_blocked" if blocking else "ai_candidate_handoff_readiness_passed",row,{"blocking_reasons":blocking});return self._handoff(row)

    def create_candidate(self,handoff_id:uuid.UUID):
        h=self.db.get(ResearchCandidateHandoff,handoff_id)
        if not h:raise LookupError("handoff not found")
        if h.created_candidate_id:
            c=ResearchCandidateService(self.db).get(h.created_candidate_id);return c
        if h.status!="readiness_passed" or h.blocking_reasons:raise ValueError("handoff readiness must pass before candidate creation")
        val=self.db.get(BlueprintValidationRun,h.validation_id);bp=self.db.get(AIStrategyBlueprint,h.blueprint_id);v=self.db.get(AIStrategyVariant,h.variant_id) if h.variant_id else None;logic=v or bp
        # Reuse existing Phase-3 candidate service by creating deterministic governance bridge records.
        bridge={"handoff_id":str(h.id),"validation_id":str(val.id),"blueprint_id":str(bp.id),"variant_id":str(v.id) if v else None,"strategy_definition":h.strategy_definition,"parameters":h.parameter_values,"provenance":h.configuration}
        hh=canonical_hash(bridge)
        hyp=self.db.execute(select(ResearchHypothesis).where(ResearchHypothesis.hypothesis_type=="strategy_filter",ResearchHypothesis.hypothesis_version=="1.0.0",ResearchHypothesis.configuration_hash==hh)).scalar_one_or_none()
        if not hyp:
            hyp=ResearchHypothesis(hypothesis_type="strategy_filter",title=f"Phase-4 handoff: {getattr(logic,'variant_name',bp.name)}",description="Deterministic governance bridge from validated Phase-4 research into Phase-3 candidate promotion gates.",status="validated",strategy_name=bp.base_strategy_name,strategy_version=bp.base_strategy_version,symbol=logic.symbol_scope[0] if logic.symbol_scope else None,timeframe=logic.timeframe_scope[0] if logic.timeframe_scope else None,regime=logic.regime_scope[0] if len(logic.regime_scope)==1 else None,feature_conditions={"requirements":logic.feature_requirements},entry_conditions=logic.entry_logic,exit_conditions=logic.exit_logic,risk_conditions=logic.risk_constraints,evidence_summary={"phase4_handoff":bridge},source_metrics=val.combined_metrics or {},sample_size=val.simulated_trade_count,confidence_score=D(str(val.score)),priority_score=D(str(h.readiness_score)),hypothesis_version="1.0.0",configuration=bridge,configuration_hash=hh)
            self.db.add(hyp);self.db.flush()
        ecfg={"phase4_handoff_id":str(h.id),"source_validation_id":str(val.id),"source_validation_hash":val.configuration_hash,"evidence_outcome_ids":[],"candidate_parameters":h.parameter_values}
        eh=canonical_hash(ecfg);exp=self.db.execute(select(ResearchExperiment).where(ResearchExperiment.hypothesis_id==hyp.id,ResearchExperiment.experiment_type=="hypothesis_validation",ResearchExperiment.experiment_version=="1.0.0",ResearchExperiment.configuration_hash==eh)).scalar_one_or_none()
        if not exp:
            exp=ResearchExperiment(hypothesis_id=hyp.id,experiment_type="hypothesis_validation",status="completed",symbol=hyp.symbol,timeframe=hyp.timeframe,strategy_name=hyp.strategy_name,strategy_version=hyp.strategy_version,train_start=val.train_start,train_end=val.train_end,validation_start=val.validation_start,validation_end=val.validation_end,configuration=ecfg,configuration_hash=eh,experiment_version="1.0.0",hypothesis_version=hyp.hypothesis_version,hypothesis_configuration_hash=hyp.configuration_hash,sample_size=val.simulated_trade_count,baseline_sample_size=0,result_metrics={"combined":val.combined_metrics,"train":val.train_metrics,"validation":val.validation_metrics,"phase4_validation_id":str(val.id)},baseline_metrics={},comparison_metrics={"candidate_parameters":h.parameter_values},score=val.score,stability_score=val.stability_score,data_quality_score=val.data_quality_score,passed=True,failure_reasons=[],started_at=val.started_at,completed_at=val.completed_at or datetime.now(timezone.utc));self.db.add(exp);self.db.commit();self.db.refresh(exp)
        candidate=ResearchCandidateService(self.db).create(CandidateCreateRequest(source_experiment_id=exp.id,name=f"Research candidate: {getattr(logic,'variant_name',bp.name)}",description=f"Created explicitly from Phase-4 handoff {h.id}; requires Phase-3 promotion evaluation and explicit governance review."))
        h.created_candidate_id=candidate.id;h.status="candidate_created";self.db.commit();self._observe("ai_candidate_handoff_candidate_created",h,{"candidate_id":str(candidate.id),"candidate_status":candidate.status,"promotion_required":True});return candidate

    def reject_handoff(self,id):
        h=self.db.get(ResearchCandidateHandoff,id)
        if not h:raise LookupError("handoff not found")
        if h.created_candidate_id:raise ValueError("candidate-created handoff cannot be rejected")
        h.status="rejected";self.db.commit();self.db.refresh(h);self._observe("ai_candidate_handoff_rejected",h,{});return self._handoff(h)
    def handoffs(self,source_type=None,blueprint=None,variant=None,validation=None,shadow_session=None,status=None,minimum_readiness=None,symbol=None,timeframe=None,regime=None,limit=100,offset=0):
        q=select(ResearchCandidateHandoff)
        for col,val in [(ResearchCandidateHandoff.source_type,source_type),(ResearchCandidateHandoff.blueprint_id,blueprint),(ResearchCandidateHandoff.variant_id,variant),(ResearchCandidateHandoff.validation_id,validation),(ResearchCandidateHandoff.shadow_session_id,shadow_session),(ResearchCandidateHandoff.status,status)]:
            if val is not None:q=q.where(col==val)
        if minimum_readiness is not None:q=q.where(ResearchCandidateHandoff.readiness_score>=minimum_readiness)
        rows=self.db.execute(q.order_by(ResearchCandidateHandoff.created_at.desc()).offset(offset).limit(limit)).scalars().all()
        if symbol:rows=[r for r in rows if symbol in r.symbol_scope]
        if timeframe:rows=[r for r in rows if timeframe in r.timeframe_scope]
        if regime:rows=[r for r in rows if regime in r.regime_scope]
        return [self._handoff(r) for r in rows]
    def handoff(self,id):
        r=self.db.get(ResearchCandidateHandoff,id);return self._handoff(r) if r else None
    def readiness(self,id):
        h=self.db.get(ResearchCandidateHandoff,id)
        if not h:raise LookupError("handoff not found")
        promotion=None
        if h.created_candidate_id:promotion=ResearchCandidateService(self.db).promotion(h.created_candidate_id)
        return {"handoff_id":h.id,"status":h.status,"readiness_score":h.readiness_score,"blocking_reasons":h.blocking_reasons,"warnings":h.warnings,"validation":h.validation_summary,"shadow":h.shadow_summary,"regime":h.regime_summary,"portfolio":h.portfolio_summary,"risk_constraints":h.risk_constraints,"protection_requirements":h.protection_requirements,"created_candidate_id":h.created_candidate_id,"promotion":promotion,"message":"Demo readiness does not mean Demo activation.","research_only":True}

    def _observe(self,event_type,obj,context):
        try:
            row=ResearchObservation(event_type=event_type,source="ai_shadow_handoff",exchange=getattr(obj,"exchange",None),symbol=(obj.symbol_scope[0] if getattr(obj,"symbol_scope",None) else None),timeframe=(obj.timeframe_scope[0] if getattr(obj,"timeframe_scope",None) else None),decision_context=context,context={"research_only":True});self.db.add(row);self.db.commit()
        except Exception:self.db.rollback()
    @staticmethod
    def _session(r):return ShadowSessionRead.model_validate(r,from_attributes=True)
    @staticmethod
    def _trade(r):return ShadowTradeRead.model_validate(r,from_attributes=True)
    @staticmethod
    def _handoff(r):return HandoffRead.model_validate(r,from_attributes=True)
