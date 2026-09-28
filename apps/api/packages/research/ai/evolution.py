from __future__ import annotations
import copy, hashlib, json, math, os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models import AIStrategyBlueprint, AIStrategyVariant, AIStrategyEvolutionRun, BlueprintValidationRun, ChampionChallengerComparison
from packages.research.models import ObservationCreate
from packages.research.service import ResearchObservationService
from .validation import BlueprintValidationService, BlueprintValidationRequest, ValidationRead
from .discovery import CODE_PATTERNS, FUTURE_PATTERNS, RISK_BLOCK_PATTERNS
from .schemas import ALLOWED_INDICATORS
from .provider import ResearchAIProvider
from .gemini_provider import GeminiResearchProvider

GENERATION_VERSION="1.0.0"; COMPARISON_VERSION="1.0.0"
VARIANT_TYPES={"parameter_variant","entry_filter_variant","exit_variant","regime_filter_variant","volatility_filter_variant","execution_cost_variant","risk_constraint_variant","simplified_variant","combined_variant"}
VARIANT_STATUSES={"generated","queued_for_validation","validated","challenger","champion","rejected","archived"}
RUN_TYPES={"parameter_refinement","robustness_improvement","drawdown_reduction","execution_cost_reduction","complexity_reduction","regime_adaptation","general_evolution"}
GENERATION_METHODS={"neighboring_parameter_search","conservative_parameter_shift","entry_filter_addition","entry_filter_removal","exit_parameter_adjustment","regime_filter_adjustment","complexity_reduction","risk_constraint_tightening","ai_assisted"}

def canonical_hash(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def _env_int(n,d,lo,hi):
    try:v=int(os.getenv(n,str(d)))
    except ValueError:v=d
    return max(lo,min(hi,v))
def _env_float(n,d,lo,hi):
    try:v=float(os.getenv(n,str(d)))
    except ValueError:v=d
    return max(lo,min(hi,v)) if math.isfinite(v) else d

def _f(v): return float(v or 0)

class EvolutionRunRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    source_blueprint_id: UUID
    source_validation_id: UUID
    run_type: str="general_evolution"
    requested_variants: int=Field(default=5,ge=1,le=100)
    allow_failed_source: bool=False
    use_ai: bool=False

class CompareRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    challenger_variant_id: UUID
    challenger_validation_id: UUID
    champion_validation_id: UUID
    champion_variant_id: UUID|None=None

class VariantRead(BaseModel):
    id:UUID; source_blueprint_id:UUID; parent_variant_id:UUID|None; source_validation_id:UUID|None; evolution_run_id:UUID|None
    variant_type:str; status:str; generation_method:str; generation_version:str; variant_name:str; description:str
    symbol_scope:list[Any]; timeframe_scope:list[Any]; regime_scope:list[Any]; feature_requirements:list[Any]; indicator_requirements:list[Any]
    entry_logic:dict[str,Any]; exit_logic:dict[str,Any]; protection_logic:dict[str,Any]; risk_constraints:dict[str,Any]
    parameter_values:dict[str,Any]; parameter_space_reference:dict[str,Any]; mutation_summary:dict[str,Any]; changed_fields:list[Any]
    evidence_summary:dict[str,Any]; lineage:dict[str,Any]; complexity:str; estimated_parameter_combinations:int
    configuration:dict[str,Any]; configuration_hash:str; created_at:datetime; updated_at:datetime

class EvolutionRunRead(BaseModel):
    id:UUID; source_blueprint_id:UUID; source_validation_id:UUID; run_type:str; status:str; generation_version:str
    requested_variants:int; generated_variants:int; validated_variants:int; rejected_variants:int
    champion_before:UUID|None; champion_after:UUID|None; configuration:dict[str,Any]; configuration_hash:str; warnings:list[Any]; failure_reason:str|None
    started_at:datetime; completed_at:datetime|None; created_at:datetime

class ComparisonRead(BaseModel):
    id:UUID; source_blueprint_id:UUID; champion_variant_id:UUID|None; champion_validation_id:UUID; challenger_variant_id:UUID; challenger_validation_id:UUID; comparison_version:str
    comparison_scope:dict[str,Any]; configuration:dict[str,Any]; configuration_hash:str; champion_metrics:dict[str,Any]; challenger_metrics:dict[str,Any]; difference_metrics:dict[str,Any]
    performance_score_difference:float; stability_difference:float; drawdown_difference:float; expectancy_difference:float; profit_factor_difference:float; execution_cost_difference:float; overfit_risk_difference:float
    challenger_wins:bool; decision:str; decision_reasons:list[Any]; warnings:list[Any]; created_at:datetime

class StrategyEvolutionService:
    """Bounded strategy evolution research. It has no exchange/order/bot/risk execution capability."""
    def __init__(self,db:Session,provider:ResearchAIProvider|None=None):self.db=db;self.provider=provider or GeminiResearchProvider()

    def create_run(self,req:EvolutionRunRequest)->EvolutionRunRead:
        if req.run_type not in RUN_TYPES:raise ValueError("unsupported evolution run type")
        bp=self.db.get(AIStrategyBlueprint,req.source_blueprint_id)
        if not bp or bp.status!="accepted_for_validation":raise ValueError("source blueprint must be accepted_for_validation")
        src=self.db.get(BlueprintValidationRun,req.source_validation_id)
        if not src or src.blueprint_id!=bp.id or src.status!="completed":raise ValueError("completed source blueprint validation required")
        if not src.passed and not req.allow_failed_source:raise ValueError("failed source validation requires explicit diagnostic opt-in")
        maxv=_env_int("AI_EVOLUTION_MAX_VARIANTS_PER_GENERATION",10,1,100)
        requested=min(req.requested_variants,maxv)
        cfg={"generation_version":GENERATION_VERSION,"source_blueprint_hash":bp.configuration_hash,"source_validation_id":str(src.id),"source_validation_passed":src.passed,"run_type":req.run_type,"requested_variants":requested,"allow_failed_source":req.allow_failed_source,"use_ai":req.use_ai,"max_variants":maxv,"max_changed_fields":_env_int("AI_EVOLUTION_MAX_CHANGED_FIELDS",3,1,20),"max_generations_per_request":_env_int("AI_EVOLUTION_MAX_GENERATIONS_PER_REQUEST",1,1,1)}
        h=canonical_hash(cfg)
        existing=self.db.execute(select(AIStrategyEvolutionRun).where(AIStrategyEvolutionRun.source_blueprint_id==bp.id,AIStrategyEvolutionRun.source_validation_id==src.id,AIStrategyEvolutionRun.generation_version==GENERATION_VERSION,AIStrategyEvolutionRun.configuration_hash==h)).scalar_one_or_none()
        if existing:return self._run_read(existing)
        row=AIStrategyEvolutionRun(source_blueprint_id=bp.id,source_validation_id=src.id,run_type=req.run_type,status="running",generation_version=GENERATION_VERSION,requested_variants=requested,generated_variants=0,validated_variants=0,rejected_variants=0,champion_before=self._champion_id(bp.id),champion_after=self._champion_id(bp.id),configuration=cfg,configuration_hash=h,warnings=[],started_at=datetime.now(timezone.utc))
        self.db.add(row);self.db.commit();self.db.refresh(row);self._observe("ai_strategy_evolution_started",bp,row=row)
        try:
            specs=self._deterministic_specs(bp,src,req.run_type,requested)
            if req.use_ai:
                # Reserve a bounded share for exactly one provider call; never recurse.
                ai_count=max(1,min(requested,len(specs) if specs else requested))
                ai_specs=self._ai_specs(bp,src,ai_count)
                specs=(specs[:max(0,requested-len(ai_specs))]+ai_specs)[:requested]
            made=[]
            for spec in specs[:requested]:
                try: made.append(self._persist_variant(bp,src,row,spec))
                except ValueError as exc: row.rejected_variants+=1; row.warnings=sorted(set(row.warnings+[str(exc)]))
            row.generated_variants=len({v.id for v in made}); row.status="completed";row.completed_at=datetime.now(timezone.utc);row.champion_after=self._champion_id(bp.id);self.db.commit();self.db.refresh(row);self._observe("ai_strategy_evolution_completed",bp,row=row)
        except Exception as exc:
            self.db.rollback(); row=self.db.get(AIStrategyEvolutionRun,row.id); row.status="failed";row.failure_reason=f"evolution_error:{type(exc).__name__}";row.completed_at=datetime.now(timezone.utc);self.db.commit();self._observe("ai_strategy_evolution_failed",bp,row=row)
        return self._run_read(row)

    def _deterministic_specs(self,bp,src,run_type,count):
        out=[]; params=src.parameter_set or {}
        # Small neighboring parameter shifts; deterministic order.
        for name,val in sorted(params.items()):
            if isinstance(val,(int,float)) and math.isfinite(float(val)):
                spec=(bp.parameter_space or {}).get(name,{}) if isinstance(bp.parameter_space,dict) else {}
                candidates=[]
                values=spec.get("values") if isinstance(spec,dict) else None
                if isinstance(values,list) and values:
                    nums=[float(x) for x in values if isinstance(x,(int,float)) and math.isfinite(float(x))]
                    candidates=sorted({x for x in nums if x!=float(val)}, key=lambda x:(abs(x-float(val)),x))[:2]
                else:
                    step=spec.get("step") if isinstance(spec,dict) else None
                    delta=float(step) if isinstance(step,(int,float)) and float(step)>0 else max(abs(float(val))*0.05,1.0 if isinstance(val,int) else 0.01)
                    lo=spec.get("min") if isinstance(spec,dict) else None; hi=spec.get("max") if isinstance(spec,dict) else None
                    for sign in (-1,1):
                        x=float(val)+sign*delta
                        if isinstance(lo,(int,float)) and x<float(lo)-1e-12:continue
                        if isinstance(hi,(int,float)) and x>float(hi)+1e-12:continue
                        candidates.append(x)
                for x in candidates:
                    out.append({"type":"parameter_variant","method":"neighboring_parameter_search","changes":{"parameter_values":{**params,name:round(x,8)}},"summary":{"parameter":name,"from":val,"to":round(x,8)}})
        if run_type in {"complexity_reduction","general_evolution","robustness_improvement"}:
            logic=copy.deepcopy(bp.entry_logic); rules=list(logic.get("all",[]));
            if len(rules)>1:out.append({"type":"simplified_variant","method":"complexity_reduction","changes":{"entry_logic":{"all":rules[:-1],"any":logic.get("any",[])}},"summary":{"removed_entry_conditions":1}})
        regimes=list(bp.regime_scope or [])
        rp=src.combined_metrics.get("regime_performance",{}) if isinstance(src.combined_metrics,dict) else {}
        if rp:
            good=sorted(rp,key=lambda k:(-_f(rp[k].get("expectancy")),k))[:max(1,len(rp)-1)]
            if good and good!=regimes:out.append({"type":"regime_filter_variant","method":"regime_filter_adjustment","changes":{"regime_scope":good},"summary":{"allowed_regimes":good}})
        # Conservative risk tightening only: every numeric maximum may only move downward.
        risk=copy.deepcopy(bp.risk_constraints or {}); changed=False
        for k,val in list(risk.items()):
            if k.startswith("max_") and isinstance(val,(int,float)):
                risk[k]=round(float(val)*0.9,8);changed=True
        if changed:out.append({"type":"risk_constraint_variant","method":"risk_constraint_tightening","changes":{"risk_constraints":risk},"summary":{"conservative":True}})
        # Controlled exit adjustment gives a deterministic challenger even when a
        # blueprint has no parameter space or removable entry filter.
        exit_logic=copy.deepcopy(bp.exit_logic or {})
        if isinstance(exit_logic.get("take_profit_pct"),(int,float)) and float(exit_logic["take_profit_pct"])>0:
            exit_logic["take_profit_pct"]=round(float(exit_logic["take_profit_pct"])*1.05,8)
            out.append({"type":"exit_variant","method":"exit_parameter_adjustment","changes":{"exit_logic":exit_logic},"summary":{"take_profit_shift":"+5% relative research adjustment"}})
        # Execution-aware metadata variant when costs are meaningful.
        drag=_f((src.execution_cost_metrics or {}).get("cost_drag_ratio"))
        if drag>0:out.append({"type":"execution_cost_variant","method":"conservative_parameter_shift","changes":{"mutation_summary":{"cost_drag_source":drag}},"summary":{"execution_cost_focus":True}})
        # Deduplicate specs deterministically.
        seen=set();result=[]
        for x in out:
            sig=canonical_hash(x)
            if sig not in seen:seen.add(sig);result.append(x)
        return result[:count]

    def _ai_specs(self,bp,src,count):
        if count<=0:return []
        if not self.provider.configured:raise ValueError("AI provider not configured for AI-assisted evolution")
        context={"blueprint_id":str(bp.id),"validation_id":str(src.id),"parameter_set":src.parameter_set,"validation_metrics":src.validation_metrics,"stability":str(src.stability_score),"overfit_risk":str(src.overfit_risk_score),"allowed_methods":sorted(GENERATION_METHODS-{"ai_assisted"}),"max_variants":count}
        data=self.provider.analyze_research_context(context=context,prompt="Suggest bounded research-only strategy mutations as JSON object with variants list. Never add code, unsupported indicators, future data, risk bypass, or trading activation.")
        variants=data.get("variants",[]) if isinstance(data,dict) else []
        out=[]
        for raw in variants[:count]:
            if not isinstance(raw,dict):continue
            out.append({"type":raw.get("variant_type","combined_variant"),"method":"ai_assisted","changes":raw.get("changes",{}),"summary":raw.get("summary",{})})
        return out

    def _persist_variant(self,bp,src,run,spec):
        vt=spec.get("type"); method=spec.get("method")
        if vt not in VARIANT_TYPES or method not in GENERATION_METHODS:raise ValueError("unsupported mutation")
        # Reject unsafe AI/deterministic mutation payloads before selectively copying fields.
        import re
        raw_blob=json.dumps(spec,sort_keys=True).lower()
        if any(re.search(p,raw_blob,re.I) for p in CODE_PATTERNS):raise ValueError("code_generation_rejected")
        if any(x in raw_blob for x in FUTURE_PATTERNS):raise ValueError("future_data_rejected")
        if any(x in raw_blob for x in RISK_BLOCK_PATTERNS):raise ValueError("risk_or_execution_bypass_rejected")
        base={"symbol_scope":copy.deepcopy(bp.symbol_scope),"timeframe_scope":copy.deepcopy(bp.timeframe_scope),"regime_scope":copy.deepcopy(bp.regime_scope),"feature_requirements":copy.deepcopy(bp.feature_requirements),"indicator_requirements":copy.deepcopy(bp.indicator_requirements),"entry_logic":copy.deepcopy(bp.entry_logic),"exit_logic":copy.deepcopy(bp.exit_logic),"protection_logic":copy.deepcopy(bp.protection_logic),"risk_constraints":copy.deepcopy(bp.risk_constraints),"parameter_values":copy.deepcopy(src.parameter_set or {}),"parameter_space_reference":copy.deepcopy(bp.parameter_space)}
        changes=copy.deepcopy(spec.get("changes") or {})
        changed=[k for k in changes if k in base]
        for k in changed:base[k]=changes[k]
        maxchg=_env_int("AI_EVOLUTION_MAX_CHANGED_FIELDS",3,1,20)
        if len(changed)>maxchg:raise ValueError("mutation_budget_exceeded")
        self._validate_mutation(bp,base)
        complexity=self._complexity(base); combos=max(1,len(src.parameter_results or []) or 1)
        cfg={"generation_version":GENERATION_VERSION,"source_blueprint_id":str(bp.id),"source_validation_id":str(src.id),"parent_variant_id":None,"variant_type":vt,"generation_method":method,"changed_fields":changed,"logic":{k:base[k] for k in ("entry_logic","exit_logic","protection_logic","risk_constraints")},"parameter_values":base["parameter_values"],"scopes":{k:base[k] for k in ("symbol_scope","timeframe_scope","regime_scope")}}
        h=canonical_hash(cfg)
        existing=self.db.execute(select(AIStrategyVariant).where(AIStrategyVariant.source_blueprint_id==bp.id,AIStrategyVariant.generation_version==GENERATION_VERSION,AIStrategyVariant.configuration_hash==h)).scalar_one_or_none()
        if existing:return existing
        lineage={"source_blueprint_id":str(bp.id),"source_validation_id":str(src.id),"source_validation_passed":src.passed,"evolution_run_id":str(run.id),"validation_ids":[]}
        row=AIStrategyVariant(source_blueprint_id=bp.id,source_validation_id=src.id,evolution_run_id=run.id,variant_type=vt,status="generated",generation_method=method,generation_version=GENERATION_VERSION,variant_name=f"{bp.name} — {vt}",description=f"Research-only {vt} generated via {method}; improvement is unproven until validation.",**base,mutation_summary={**(spec.get("summary") or {}),**(changes.get("mutation_summary") or {})},changed_fields=changed,evidence_summary={"source_validation_passed":src.passed,"source_score":str(src.score),"source_stability":str(src.stability_score),"source_overfit_risk":str(src.overfit_risk_score)},lineage=lineage,complexity=complexity,estimated_parameter_combinations=combos,configuration=cfg,configuration_hash=h)
        self.db.add(row)
        try:self.db.commit()
        except IntegrityError:self.db.rollback();return self.db.execute(select(AIStrategyVariant).where(AIStrategyVariant.configuration_hash==h)).scalar_one()
        self.db.refresh(row);self._observe("ai_strategy_variant_generated",bp,variant=row);return row

    def _validate_mutation(self,bp,v):
        blob=json.dumps(v,sort_keys=True).lower()
        import re
        if any(re.search(p,blob,re.I) for p in CODE_PATTERNS):raise ValueError("code_generation_rejected")
        if any(x in blob for x in FUTURE_PATTERNS):raise ValueError("future_data_rejected")
        if any(x in blob for x in RISK_BLOCK_PATTERNS):raise ValueError("risk_or_execution_bypass_rejected")
        bad={str(x).lower() for x in v["indicator_requirements"]}-{str(x).lower() for x in ALLOWED_INDICATORS}
        if bad:raise ValueError("unsupported_indicator_rejected")
        if v["protection_logic"].get("stop_loss_required") is False:raise ValueError("mandatory_protection_cannot_be_removed")
        # Numeric max-risk style constraints may only stay equal or tighten.
        for k,val in (v["risk_constraints"] or {}).items():
            old=(bp.risk_constraints or {}).get(k)
            if k.startswith("max_") and isinstance(old,(int,float)) and isinstance(val,(int,float)) and float(val)>float(old)+1e-12:raise ValueError("risk_constraint_may_not_be_relaxed")
            if k.startswith("min_") and isinstance(old,(int,float)) and isinstance(val,(int,float)) and float(val)<float(old)-1e-12:raise ValueError("risk_constraint_may_not_be_relaxed")

    @staticmethod
    def _complexity(v):
        conditions=len(v["entry_logic"].get("all",[]))+len(v["entry_logic"].get("any",[]))+len(v["exit_logic"] or {})
        score=len(v["indicator_requirements"])+conditions+2*len(v["parameter_values"])+2*(1 if v["regime_scope"] else 0)
        return "low" if score<=8 else "medium" if score<=18 else "high" if score<=30 else "excessive"

    def validate_variant(self,variant_id:UUID,req:BlueprintValidationRequest)->ValidationRead:
        v=self.db.get(AIStrategyVariant,variant_id)
        if not v:raise LookupError("AI strategy variant not found")
        if v.status in {"rejected","archived"}:raise ValueError("rejected/archived variant cannot validate")
        v.status="queued_for_validation";self.db.commit()
        result=BlueprintValidationService(self.db).validate_variant(v,req)
        row=self.db.get(BlueprintValidationRun,result.id)
        v=self.db.get(AIStrategyVariant,variant_id);v.status="validated" if row.status=="completed" else "rejected"
        lin=dict(v.lineage or {}); ids=list(lin.get("validation_ids",[]));
        if str(row.id) not in ids:ids.append(str(row.id))
        lin["validation_ids"]=ids;lin["latest_validation_id"]=str(row.id);v.lineage=lin
        if v.evolution_run_id:
            er=self.db.get(AIStrategyEvolutionRun,v.evolution_run_id)
            if er:er.validated_variants+=int(row.status=="completed")
        self.db.commit();self._observe("ai_strategy_variant_validation_completed",self.db.get(AIStrategyBlueprint,v.source_blueprint_id),variant=v,validation=row)
        return result

    def variant_validations(self,variant_id):
        v=self.db.get(AIStrategyVariant,variant_id)
        if not v:raise LookupError("AI strategy variant not found")
        ids=[UUID(x) for x in (v.lineage or {}).get("validation_ids",[])]; service=BlueprintValidationService(self.db)
        return [service.get(x) for x in ids if service.get(x)]

    def compare(self,req:CompareRequest)->ComparisonRead:
        cv=self.db.get(AIStrategyVariant,req.challenger_variant_id); chal=self.db.get(BlueprintValidationRun,req.challenger_validation_id); champ=self.db.get(BlueprintValidationRun,req.champion_validation_id)
        if not cv or not chal or not champ:raise LookupError("comparison source not found")
        if chal.status!="completed" or champ.status!="completed":raise ValueError("completed validations required")
        if cv.source_blueprint_id!=chal.blueprint_id or chal.blueprint_id!=champ.blueprint_id:raise ValueError("incompatible comparison blueprint scope")
        champion_variant=self.db.get(AIStrategyVariant,req.champion_variant_id) if req.champion_variant_id else None
        if champion_variant and champion_variant.source_blueprint_id!=cv.source_blueprint_id:raise ValueError("incompatible champion variant")
        scope_keys=("data_scope","fee_bps","slippage_bps","execution_convention","intrabar_conflict_policy","gates")
        a={k:champ.configuration.get(k) for k in scope_keys}; b={k:chal.configuration.get(k) for k in scope_keys}
        boundaries=(champ.train_start,champ.train_end,champ.validation_start,champ.validation_end); boundaries2=(chal.train_start,chal.train_end,chal.validation_start,chal.validation_end)
        if a!=b or boundaries!=boundaries2 or champ.symbol_scope!=chal.symbol_scope or champ.timeframe_scope!=chal.timeframe_scope or champ.regime_scope!=chal.regime_scope:raise ValueError("incompatible comparison scope")
        cm=champ.validation_metrics if champ.validation_metrics.get("trade_count",0) else champ.combined_metrics; xm=chal.validation_metrics if chal.validation_metrics.get("trade_count",0) else chal.combined_metrics
        diffs={"score":_f(chal.score)-_f(champ.score),"stability":_f(chal.stability_score)-_f(champ.stability_score),"drawdown":_f(xm.get("max_drawdown"))-_f(cm.get("max_drawdown")),"expectancy":_f(xm.get("expectancy"))-_f(cm.get("expectancy")),"profit_factor":_f(xm.get("profit_factor"))-_f(cm.get("profit_factor")),"execution_cost":_f(chal.execution_cost_metrics.get("cost_drag"))-_f(champ.execution_cost_metrics.get("cost_drag")),"overfit_risk":_f(chal.overfit_risk_score)-_f(champ.overfit_risk_score)}
        composite=self._comparison_score(chal,xm)-self._comparison_score(champ,cm); margin=_env_float("AI_EVOLUTION_MIN_CHALLENGER_IMPROVEMENT",0.03,0,1)
        warnings=[]; reasons=[]
        if xm.get("trade_count",0)<max(5,cm.get("trade_count",0)*0.5):warnings.append("challenger_sample_materially_smaller")
        if _f(chal.overfit_risk_score)>_f(champ.overfit_risk_score)+0.10:warnings.append("challenger_overfit_risk_increased")
        wins=composite>=margin and _f(chal.overfit_risk_score)<=max(0.8,_f(champ.overfit_risk_score)+0.05) and _f(chal.data_quality_score)>=_f(champ.data_quality_score)-0.05
        if composite<margin:reasons.append("minimum_improvement_margin_not_met")
        if not wins and "minimum_improvement_margin_not_met" not in reasons:reasons.append("risk_or_quality_tradeoff_not_acceptable")
        decision="challenger_promoted_to_research_champion" if wins else "champion_retained"
        scope={"blueprint_id":str(cv.source_blueprint_id),"symbol_scope":chal.symbol_scope,"timeframe_scope":chal.timeframe_scope,"regime_scope":chal.regime_scope,"data_scope":a["data_scope"],"boundaries":[str(x) if x else None for x in boundaries]}
        cfg={"comparison_version":COMPARISON_VERSION,"scope":scope,"minimum_improvement":margin,"champion_validation_id":str(champ.id),"challenger_validation_id":str(chal.id),"champion_variant_id":str(req.champion_variant_id) if req.champion_variant_id else None,"challenger_variant_id":str(cv.id)}; h=canonical_hash(cfg)
        old=self.db.execute(select(ChampionChallengerComparison).where(ChampionChallengerComparison.source_blueprint_id==cv.source_blueprint_id,ChampionChallengerComparison.challenger_variant_id==cv.id,ChampionChallengerComparison.comparison_version==COMPARISON_VERSION,ChampionChallengerComparison.configuration_hash==h)).scalar_one_or_none()
        if old:return self._comparison_read(old)
        row=ChampionChallengerComparison(source_blueprint_id=cv.source_blueprint_id,champion_variant_id=req.champion_variant_id,champion_validation_id=champ.id,challenger_variant_id=cv.id,challenger_validation_id=chal.id,comparison_version=COMPARISON_VERSION,comparison_scope=scope,configuration=cfg,configuration_hash=h,champion_metrics=cm,challenger_metrics=xm,difference_metrics={**diffs,"composite_improvement":round(composite,8)},performance_score_difference=Decimal(str(diffs["score"])),stability_difference=Decimal(str(diffs["stability"])),drawdown_difference=Decimal(str(diffs["drawdown"])),expectancy_difference=Decimal(str(diffs["expectancy"])),profit_factor_difference=Decimal(str(diffs["profit_factor"])),execution_cost_difference=Decimal(str(diffs["execution_cost"])),overfit_risk_difference=Decimal(str(diffs["overfit_risk"])),challenger_wins=wins,decision=decision,decision_reasons=reasons,warnings=warnings)
        self.db.add(row);self.db.commit();self.db.refresh(row);bp=self.db.get(AIStrategyBlueprint,cv.source_blueprint_id)
        self._observe("ai_champion_challenger_compared",bp,variant=cv,comparison=row)
        if wins:
            # Maintain a single research champion inside the blueprint family.
            others=self.db.execute(select(AIStrategyVariant).where(AIStrategyVariant.source_blueprint_id==cv.source_blueprint_id,AIStrategyVariant.status=="champion",AIStrategyVariant.id!=cv.id)).scalars().all()
            for old in others:old.status="challenger"
            cv.status="champion";self.db.commit();self._observe("ai_research_champion_changed",bp,variant=cv,comparison=row)
        elif cv.status!="champion":cv.status="challenger";self.db.commit()
        return self._comparison_read(row)

    @staticmethod
    def _comparison_score(v,m):
        exp=(math.tanh(_f(m.get("expectancy"))/10)+1)/2;pf=min(2,_f(m.get("profit_factor")))/2;dd=1/(1+max(0,_f(m.get("max_drawdown")))/100);sample=min(1,m.get("trade_count",0)/20);cost=1-min(1,_f(v.execution_cost_metrics.get("cost_drag")));return 0.25*_f(v.score)+0.15*exp+0.1*pf+0.1*dd+0.15*_f(v.stability_score)+0.1*_f(v.data_quality_score)+0.05*cost+0.05*(1-_f(v.overfit_risk_score))+0.05*sample

    def champion(self,blueprint_id):
        bp=self.db.get(AIStrategyBlueprint,blueprint_id)
        if not bp:raise LookupError("AI strategy blueprint not found")
        row=self.db.execute(select(AIStrategyVariant).where(AIStrategyVariant.source_blueprint_id==blueprint_id,AIStrategyVariant.status=="champion").order_by(AIStrategyVariant.updated_at.desc(),AIStrategyVariant.id.desc())).scalars().first()
        return self._variant_read(row) if row else None
    def _champion_id(self,bid):
        x=self.db.execute(select(AIStrategyVariant.id).where(AIStrategyVariant.source_blueprint_id==bid,AIStrategyVariant.status=="champion").order_by(AIStrategyVariant.updated_at.desc())).scalar_one_or_none();return x
    def get_variant(self,vid):
        r=self.db.get(AIStrategyVariant,vid);return self._variant_read(r) if r else None
    def list_variants(self,**f):
        q=select(AIStrategyVariant)
        for k,c in (("blueprint",AIStrategyVariant.source_blueprint_id),("variant_type",AIStrategyVariant.variant_type),("status",AIStrategyVariant.status),("complexity",AIStrategyVariant.complexity),("generation_method",AIStrategyVariant.generation_method)):
            if f.get(k) is not None:q=q.where(c==f[k])
        rows=self.db.execute(q.order_by(AIStrategyVariant.created_at.desc(),AIStrategyVariant.id.desc())).scalars().all()
        def scope(r):return (not f.get("symbol") or f["symbol"].upper() in [str(x).upper() for x in r.symbol_scope]) and (not f.get("timeframe") or f["timeframe"] in r.timeframe_scope) and (not f.get("regime") or f["regime"] in r.regime_scope)
        rows=[x for x in rows if scope(x)]
        if f.get("validation_passed") is not None:
            wanted=bool(f["validation_passed"]); filtered=[]
            for x in rows:
                vid=(x.lineage or {}).get("latest_validation_id")
                vr=self.db.get(BlueprintValidationRun,UUID(vid)) if vid else None
                if vr is not None and bool(vr.passed)==wanted:filtered.append(x)
            rows=filtered
        off=f.get("offset",0);lim=f.get("limit",100);return [self._variant_read(x) for x in rows[off:off+lim]]
    def get_run(self,rid):
        r=self.db.get(AIStrategyEvolutionRun,rid);return self._run_read(r) if r else None
    def list_runs(self,limit=100,offset=0):
        rows=self.db.execute(select(AIStrategyEvolutionRun).order_by(AIStrategyEvolutionRun.created_at.desc(),AIStrategyEvolutionRun.id.desc())).scalars().all();return [self._run_read(x) for x in rows[offset:offset+limit]]
    def get_comparison(self,cid):
        r=self.db.get(ChampionChallengerComparison,cid);return self._comparison_read(r) if r else None
    def list_comparisons(self,limit=100,offset=0):
        rows=self.db.execute(select(ChampionChallengerComparison).order_by(ChampionChallengerComparison.created_at.desc(),ChampionChallengerComparison.id.desc())).scalars().all();return [self._comparison_read(x) for x in rows[offset:offset+limit]]

    def _observe(self,event,bp,**entities):
        try:
            ctx={"blueprint_id":str(bp.id),"event":event}
            for name,obj in entities.items():ctx[f"{name}_id"]=str(obj.id);ctx[name]={k:(str(getattr(obj,k)) if isinstance(getattr(obj,k,None),(UUID,Decimal)) else getattr(obj,k,None)) for k in ("status","decision","challenger_wins","passed","score") if hasattr(obj,k)}
            ResearchObservationService(self.db).record(ObservationCreate(event_type=event,source="ai_strategy_evolution",symbol=bp.symbol_scope[0] if bp.symbol_scope else None,timeframe=bp.timeframe_scope[0] if bp.timeframe_scope else None,strategy_name=bp.base_strategy_name,context=ctx))
        except Exception:self.db.rollback()
    @staticmethod
    def _variant_read(r):return VariantRead.model_validate({k:getattr(r,k) for k in VariantRead.model_fields})
    @staticmethod
    def _run_read(r):return EvolutionRunRead.model_validate({k:getattr(r,k) for k in EvolutionRunRead.model_fields})
    @staticmethod
    def _comparison_read(r):
        d={k:getattr(r,k) for k in ComparisonRead.model_fields}
        for k in ("performance_score_difference","stability_difference","drawdown_difference","expectancy_difference","profit_factor_difference","execution_cost_difference","overfit_risk_difference"):d[k]=float(d[k])
        return ComparisonRead.model_validate(d)
