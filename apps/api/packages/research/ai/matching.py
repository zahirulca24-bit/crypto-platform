from __future__ import annotations
import hashlib,json,math,os
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from models import StrategyRegimeProfile,ResearchStrategyPortfolio,BlueprintValidationRun,BlueprintSimulatedTrade,AIStrategyBlueprint,AIStrategyVariant
from packages.research.models import ObservationCreate
from packages.research.service import ResearchObservationService

PROFILE_VERSION='1.0.0'; PORTFOLIO_VERSION='1.0.0'
REGIMES={'trending_bull','trending_bear','ranging','high_volatility','low_volatility','breakout','mean_reverting','transition','unknown'}
PORTFOLIO_TYPES={'regime_specific','multi_regime','diversified_research','low_drawdown_research','stability_weighted','equal_weight_research'}
PORTFOLIO_STATUSES={'draft','evaluated','review_required','accepted_for_research','rejected','archived'}
ALLOCATION_METHODS={'equal_weight','compatibility_weighted','stability_weighted','inverse_drawdown_weighted','composite_research_weighted'}

def canonical_hash(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def _f(x):
    try:return float(x or 0)
    except:return 0.0
def _env_float(n,d,lo=0,hi=1):
    try:v=float(os.getenv(n,str(d)))
    except:v=d
    return max(lo,min(hi,v)) if math.isfinite(v) else d
def _env_int(n,d,lo=1,hi=100):
    try:v=int(os.getenv(n,str(d)))
    except:v=d
    return max(lo,min(hi,v))

def _metrics(trades:list[BlueprintSimulatedTrade]):
    if not trades:return {'trade_count':0,'win_rate':0.0,'expectancy':0.0,'profit_factor':0.0,'max_drawdown':0.0,'net_return':0.0,'cost_drag':0.0}
    rets=[_f(t.return_pct) for t in trades]; pnls=[_f(t.net_pnl) for t in trades]; gross=[_f(t.gross_pnl) for t in trades]
    wins=[x for x in pnls if x>0]; losses=[x for x in pnls if x<0]; eq=0;peak=0;dd=0
    for p in pnls:eq+=p;peak=max(peak,eq);dd=max(dd,peak-eq)
    gp=sum(wins);gl=abs(sum(losses)); costs=sum(_f(t.simulated_fees)+_f(t.simulated_slippage) for t in trades); gross_abs=abs(sum(gross))
    return {'trade_count':len(trades),'win_rate':len(wins)/len(trades),'expectancy':sum(pnls)/len(trades),'profit_factor':gp/gl if gl else (999.0 if gp else 0.0),'max_drawdown':dd,'net_return':sum(rets),'cost_drag':costs/gross_abs if gross_abs else 0.0}

class ProfileGenerateRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    regime:str
    symbol:str|None=None; timeframe:str|None=None
    blueprint_id:UUID|None=None; variant_id:UUID|None=None

class PortfolioBuildRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str='Research Portfolio'; portfolio_type:str='regime_specific'; regime:str
    symbol:str|None=None; timeframe:str|None=None; allocation_method:str='composite_research_weighted'; requested_components:int=Field(default=5,ge=1,le=50)

class StrategyMatchingService:
    """Research simulation only. No capital, order, bot, risk or credential authority."""
    def __init__(self,db:Session):self.db=db
    def cfg(self):return {'min_regime_trades':_env_int('AI_MATCH_MIN_REGIME_TRADES',10,1,10000),'max_components':_env_int('AI_PORTFOLIO_MAX_COMPONENTS',5,1,50),'max_component_weight':_env_float('AI_PORTFOLIO_MAX_COMPONENT_WEIGHT',.40,.05,1),'max_pairwise_correlation':_env_float('AI_PORTFOLIO_MAX_PAIRWISE_CORRELATION',.85,0,1),'min_readiness_score':_env_float('AI_PORTFOLIO_MIN_READINESS_SCORE',.60,0,1),'min_component_count':2,'min_data_quality':.5,'min_robustness':.35,'max_portfolio_drawdown':30.0,'max_overfit_risk':.7,'min_expectancy':0.0}
    def _validations(self,blueprint_id=None,variant_id=None):
        q=select(BlueprintValidationRun).where(BlueprintValidationRun.status=='completed',BlueprintValidationRun.passed.is_(True))
        if blueprint_id:q=q.where(BlueprintValidationRun.blueprint_id==blueprint_id)
        rows=list(self.db.execute(q.order_by(BlueprintValidationRun.created_at,BlueprintValidationRun.id)).scalars())
        if variant_id: rows=[r for r in rows if str((r.configuration or {}).get('source_variant_id',''))==str(variant_id)]
        elif blueprint_id: rows=[r for r in rows if not (r.configuration or {}).get('source_variant_id')]
        return rows
    def generate_profile(self,req:ProfileGenerateRequest):
        if req.regime not in REGIMES:raise ValueError('unsupported regime')
        if bool(req.blueprint_id)==bool(req.variant_id):raise ValueError('provide exactly one blueprint_id or variant_id')
        source_type='variant' if req.variant_id else 'blueprint'; variant=self.db.get(AIStrategyVariant,req.variant_id) if req.variant_id else None
        bp_id=variant.source_blueprint_id if variant else req.blueprint_id; bp=self.db.get(AIStrategyBlueprint,bp_id)
        if not bp:raise LookupError('strategy source not found')
        vals=self._validations(bp_id,req.variant_id)
        if not vals:raise ValueError('no completed passing validation')
        v_ids=[v.id for v in vals]; tq=select(BlueprintSimulatedTrade).where(BlueprintSimulatedTrade.validation_run_id.in_(v_ids),BlueprintSimulatedTrade.entry_regime==req.regime)
        if req.symbol:tq=tq.where(BlueprintSimulatedTrade.symbol==req.symbol.upper())
        if req.timeframe:tq=tq.where(BlueprintSimulatedTrade.timeframe==req.timeframe)
        trades=list(self.db.execute(tq.order_by(BlueprintSimulatedTrade.entry_time,BlueprintSimulatedTrade.id)).scalars()); m=_metrics(trades); cfg=self.cfg()
        stability=sum(_f(v.stability_score) for v in vals)/len(vals); quality=sum(_f(v.data_quality_score) for v in vals)/len(vals); overfit=sum(_f(v.overfit_risk_score) for v in vals)/len(vals)
        n=m['trade_count']; sample_factor=min(1,n/cfg['min_regime_trades']); pf=min(1,m['profit_factor']/2); exp=0.5+0.5*math.tanh(m['expectancy']/10); dd=1/(1+max(0,m['max_drawdown'])/20); cost=max(0,1-m['cost_drag'])
        score=max(0,min(1,(.22*exp+.16*pf+.16*stability+.14*quality+.12*dd+.10*cost+.10*(1-overfit))*sample_factor))
        warnings=[];weak=[];strong=[]
        if n<cfg['min_regime_trades']:warnings.append('insufficient_regime_sample');weak.append('tiny_sample')
        if m['expectancy']>0:strong.append('positive_expectancy')
        else:weak.append('non_positive_expectancy')
        if quality<.5:weak.append('poor_data_quality')
        if overfit>.7:weak.append('high_overfit_risk')
        scope={'source_type':source_type,'blueprint_id':str(bp_id),'variant_id':str(req.variant_id) if req.variant_id else None,'regime':req.regime,'symbol':req.symbol,'timeframe':req.timeframe,'validation_ids':[str(x) for x in v_ids],'trade_ids':[str(t.id) for t in trades],'thresholds':cfg}
        h=canonical_hash(scope)
        old=self.db.execute(select(StrategyRegimeProfile).where(StrategyRegimeProfile.source_type==source_type,StrategyRegimeProfile.blueprint_id==bp_id,StrategyRegimeProfile.variant_id==req.variant_id,StrategyRegimeProfile.regime==req.regime,StrategyRegimeProfile.profile_version==PROFILE_VERSION,StrategyRegimeProfile.configuration_hash==h)).scalar_one_or_none()
        if old:return old
        row=StrategyRegimeProfile(source_type=source_type,blueprint_id=bp_id,variant_id=req.variant_id,profile_version=PROFILE_VERSION,symbol_scope=[req.symbol] if req.symbol else list((variant.symbol_scope if variant else bp.symbol_scope) or []),timeframe_scope=[req.timeframe] if req.timeframe else list((variant.timeframe_scope if variant else bp.timeframe_scope) or []),regime=req.regime,validation_ids=[str(x) for x in v_ids],sample_size=n,simulated_trade_count=n,expectancy=Decimal(str(m['expectancy'])),profit_factor=Decimal(str(m['profit_factor'])),win_rate=Decimal(str(m['win_rate'])),max_drawdown=Decimal(str(m['max_drawdown'])),stability_score=Decimal(str(stability)),data_quality_score=Decimal(str(quality)),overfit_risk_score=Decimal(str(overfit)),execution_cost_drag=Decimal(str(m['cost_drag'])),regime_score=Decimal(str(score)),compatibility_score=Decimal(str(score)),strengths=strong,weaknesses=weak,warnings=warnings,configuration=scope,configuration_hash=h)
        self.db.add(row);self.db.commit();self.db.refresh(row);self._obs('ai_strategy_regime_profile_generated',{'profile_id':str(row.id),'regime':req.regime,'compatibility_score':score,'warnings':warnings});return row
    def profiles(self,**kw):
        q=select(StrategyRegimeProfile)
        for k,v in kw.items():
            if v is None:continue
            if k=='minimum_compatibility':q=q.where(StrategyRegimeProfile.compatibility_score>=v)
            elif hasattr(StrategyRegimeProfile,k):q=q.where(getattr(StrategyRegimeProfile,k)==v)
        return list(self.db.execute(q.order_by(StrategyRegimeProfile.compatibility_score.desc(),StrategyRegimeProfile.id)).scalars())
    def rank(self,regime,symbol=None,timeframe=None,minimum_compatibility=0.0,maximum_overfit_risk=.7,minimum_stability=0.0):
        rows=self.profiles(regime=regime);out=[]
        for p in rows:
            if _f(p.compatibility_score)<minimum_compatibility or _f(p.overfit_risk_score)>maximum_overfit_risk or _f(p.stability_score)<minimum_stability or _f(p.data_quality_score)<.4:continue
            if symbol and p.symbol_scope and symbol.upper() not in [str(x).upper() for x in p.symbol_scope]:continue
            if timeframe and p.timeframe_scope and timeframe not in p.timeframe_scope:continue
            champion=bool(p.variant_id and self.db.get(AIStrategyVariant,p.variant_id) and self.db.get(AIStrategyVariant,p.variant_id).status=='champion')
            out.append({'profile_id':p.id,'source_type':p.source_type,'blueprint_id':p.blueprint_id,'variant_id':p.variant_id,'compatibility_score':float(p.compatibility_score),'champion':champion,'reason':'regime evidence outranks champion metadata; champion is only a secondary research signal'})
        self._obs('ai_strategy_matching_ranked',{'regime':regime,'ranked_profile_ids':[str(x['profile_id']) for x in out]});return out
    def _weights(self,profiles,method,cap):
        if not profiles:return {}
        raw=[]
        for p in profiles:
            if method=='equal_weight':x=1
            elif method=='compatibility_weighted':x=max(.001,_f(p.compatibility_score))
            elif method=='stability_weighted':x=max(.001,_f(p.stability_score))
            elif method=='inverse_drawdown_weighted':x=1/(1+max(0,_f(p.max_drawdown)))
            else:x=max(.001,_f(p.compatibility_score)*_f(p.stability_score)*_f(p.data_quality_score)*(1-_f(p.overfit_risk_score)))
            raw.append(x)
        n=len(raw)
        if n*cap<1:return {}
        w=[x/sum(raw) for x in raw]
        for _ in range(20):
            over=[i for i,x in enumerate(w) if x>cap+1e-12]
            if not over:break
            excess=sum(w[i]-cap for i in over)
            for i in over:w[i]=cap
            under=[i for i,x in enumerate(w) if x<cap-1e-12]
            s=sum(w[i] for i in under)
            if not under:break
            for i in under:w[i]+=excess*(w[i]/s if s else 1/len(under))
        w=[round(x,12) for x in w];w[-1]+=1-sum(w)
        return {str(p.id):w[i] for i,p in enumerate(profiles)}
    def _returns(self,p):
        vids=[UUID(str(x)) for x in p.validation_ids]
        rows=self.db.execute(select(BlueprintSimulatedTrade).where(BlueprintSimulatedTrade.validation_run_id.in_(vids)).order_by(BlueprintSimulatedTrade.entry_time,BlueprintSimulatedTrade.id)).scalars()
        return {t.entry_time:_f(t.return_pct) for t in rows}
    def _corr(self,a,b):
        ra,rb=self._returns(a),self._returns(b);keys=sorted(set(ra)&set(rb))
        if len(keys)<3:return None
        x=[ra[k] for k in keys];y=[rb[k] for k in keys];mx=sum(x)/len(x);my=sum(y)/len(y);num=sum((u-mx)*(v-my) for u,v in zip(x,y));dx=sum((u-mx)**2 for u in x);dy=sum((v-my)**2 for v in y)
        return num/math.sqrt(dx*dy) if dx and dy else 0.0
    def build_portfolio(self,req:PortfolioBuildRequest):
        if req.regime not in REGIMES:raise ValueError('unsupported regime')
        if req.portfolio_type not in PORTFOLIO_TYPES:raise ValueError('unsupported portfolio type')
        if req.allocation_method not in ALLOCATION_METHODS:raise ValueError('unsupported allocation method')
        cfg=self.cfg(); ranked=self.rank(req.regime,req.symbol,req.timeframe); profiles=[];warnings=[]
        for x in ranked:
            p=self.db.get(StrategyRegimeProfile,x['profile_id'])
            if p and _f(p.compatibility_score)>=.3:profiles.append(p)
            if len(profiles)>=min(req.requested_components,cfg['max_components']):break
        # correlation-aware filter
        selected=[];corr_pairs=[]
        for p in profiles:
            too=False
            for s in selected:
                c=self._corr(p,s);corr_pairs.append({'a':str(p.id),'b':str(s.id),'correlation':c})
                if c is not None and abs(c)>cfg['max_pairwise_correlation']:too=True;warnings.append('high_pairwise_correlation_excluded');break
            if not too:selected.append(p)
        weights=self._weights(selected,req.allocation_method,cfg['max_component_weight']);blocking=[]
        if selected and not weights:blocking.append('component_weight_cap_infeasible')
        n=len(selected); avgq=sum(_f(p.data_quality_score) for p in selected)/n if n else 0;rob=sum(_f(p.stability_score)*(1-_f(p.overfit_risk_score)) for p in selected)/n if n else 0;conc=max(weights.values()) if weights else 1
        known=[abs(x['correlation']) for x in corr_pairs if x['correlation'] is not None];avgcorr=sum(known)/len(known) if known else None;maxcorr=max(known) if known else None;div=1-avgcorr if avgcorr is not None else (0.5 if n>1 else 0)
        exp=sum(weights.get(str(p.id),0)*_f(p.expectancy) for p in selected);dd=sum(weights.get(str(p.id),0)*_f(p.max_drawdown) for p in selected);over=sum(weights.get(str(p.id),0)*_f(p.overfit_risk_score) for p in selected);cost=sum(weights.get(str(p.id),0)*_f(p.execution_cost_drag) for p in selected)
        readiness=max(0,min(1,.25*avgq+.25*rob+.2*(sum(_f(p.compatibility_score) for p in selected)/n if n else 0)+.15*div+.15*max(0,1-dd/50)))
        min_components=min(cfg['min_component_count'],cfg['max_components']);
        if n<min_components:blocking.append('minimum_component_count')
        if avgq<cfg['min_data_quality']:blocking.append('minimum_data_quality')
        if rob<cfg['min_robustness']:blocking.append('minimum_robustness')
        if conc>cfg['max_component_weight']+1e-9:blocking.append('maximum_concentration')
        if dd>cfg['max_portfolio_drawdown']:blocking.append('maximum_drawdown')
        if avgcorr is not None and avgcorr>cfg['max_pairwise_correlation']:blocking.append('maximum_average_correlation')
        if over>cfg['max_overfit_risk']:blocking.append('maximum_overfit_risk')
        if exp<=cfg['min_expectancy']:blocking.append('minimum_expectancy')
        if readiness<cfg['min_readiness_score']:blocking.append('minimum_readiness_score')
        if avgcorr is None and n>1:warnings.append('correlation_unavailable_insufficient_overlap')
        family_counts=defaultdict(int)
        for p in selected:family_counts[str(p.blueprint_id)]+=1
        if any(v>1 for v in family_counts.values()):warnings.append('family_concentration')
        scope={'name':req.name,'portfolio_type':req.portfolio_type,'regime':req.regime,'symbol':req.symbol,'timeframe':req.timeframe,'allocation_method':req.allocation_method,'profile_ids':[str(p.id) for p in selected],'weights':weights,'thresholds':cfg}
        h=canonical_hash(scope);old=self.db.execute(select(ResearchStrategyPortfolio).where(ResearchStrategyPortfolio.portfolio_version==PORTFOLIO_VERSION,ResearchStrategyPortfolio.configuration_hash==h)).scalar_one_or_none()
        if old:return old
        row=ResearchStrategyPortfolio(name=req.name,portfolio_version=PORTFOLIO_VERSION,portfolio_type=req.portfolio_type,status='evaluated',symbol_scope=[req.symbol] if req.symbol else [],timeframe_scope=[req.timeframe] if req.timeframe else [],regime_scope=[req.regime],source_profile_ids=[str(p.id) for p in selected],source_blueprint_ids=list(dict.fromkeys(str(p.blueprint_id) for p in selected)),source_variant_ids=[str(p.variant_id) for p in selected if p.variant_id],source_validation_ids=list(dict.fromkeys(x for p in selected for x in p.validation_ids)),component_count=n,allocation_method=req.allocation_method,allocation_weights=weights,expected_metrics={'expectancy':exp,'max_drawdown':dd,'overfit_risk':over,'execution_cost_drag':cost},diversification_metrics={'diversification_score':div},correlation_metrics={'pairs':corr_pairs,'average_correlation':avgcorr,'maximum_correlation':maxcorr,'available':avgcorr is not None},concentration_score=Decimal(str(conc)),robustness_score=Decimal(str(rob)),data_quality_score=Decimal(str(avgq)),readiness_score=Decimal(str(readiness)),warnings=warnings,blocking_reasons=list(dict.fromkeys(blocking)),configuration=scope,configuration_hash=h)
        self.db.add(row);self.db.commit();self.db.refresh(row);self._obs('ai_research_portfolio_built',{'portfolio_id':str(row.id),'component_count':n,'readiness_score':readiness,'blocking_reasons':row.blocking_reasons});self._obs('ai_research_portfolio_evaluated',{'portfolio_id':str(row.id),'expected_metrics':row.expected_metrics});return row
    def portfolios(self,status=None,regime=None,symbol=None,timeframe=None,blueprint=None,variant=None,minimum_compatibility=None,minimum_stability=None,maximum_overfit_risk=None,limit=100,offset=0):
        q=select(ResearchStrategyPortfolio)
        if status:q=q.where(ResearchStrategyPortfolio.status==status)
        rows=list(self.db.execute(q.order_by(ResearchStrategyPortfolio.created_at.desc(),ResearchStrategyPortfolio.id.desc())).scalars())
        out=[]
        for p in rows:
            if regime and regime not in p.regime_scope:continue
            if symbol and p.symbol_scope and symbol.upper() not in [str(x).upper() for x in p.symbol_scope]:continue
            if timeframe and p.timeframe_scope and timeframe not in p.timeframe_scope:continue
            if blueprint and str(blueprint) not in {str(x) for x in p.source_blueprint_ids}:continue
            if variant and str(variant) not in {str(x) for x in p.source_variant_ids}:continue
            profiles=[self.db.get(StrategyRegimeProfile,UUID(str(x))) for x in p.source_profile_ids]
            profiles=[x for x in profiles if x]
            if minimum_compatibility is not None and profiles and max(_f(x.compatibility_score) for x in profiles)<minimum_compatibility:continue
            if minimum_stability is not None and profiles and max(_f(x.stability_score) for x in profiles)<minimum_stability:continue
            if maximum_overfit_risk is not None and profiles and min(_f(x.overfit_risk_score) for x in profiles)>maximum_overfit_risk:continue
            out.append(p)
        return out[offset:offset+limit]
    def portfolio(self,pid):return self.db.get(ResearchStrategyPortfolio,pid)
    def transition(self,from_regime,to_regime,symbol=None,timeframe=None):
        before={str(x['profile_id']):x for x in self.rank(from_regime,symbol,timeframe)};after={str(x['profile_id']):x for x in self.rank(to_regime,symbol,timeframe)}
        return {'from_regime':from_regime,'to_regime':to_regime,'remain_eligible':[k for k in after if k in before],'excluded':[k for k in before if k not in after],'entered':[k for k in after if k not in before],'ranked_after':list(after.values()),'research_only':True}
    def status(self,pid,new):
        p=self.portfolio(pid)
        if not p:raise LookupError('portfolio not found')
        allowed={'review_required':['evaluated'],'accepted_for_research':['review_required'],'rejected':['evaluated','review_required']}
        if new not in allowed or p.status not in allowed[new]:raise ValueError('invalid portfolio research status transition')
        if new=='review_required' and p.blocking_reasons:raise ValueError('blocked portfolio cannot request review')
        p.status=new;self.db.commit();self.db.refresh(p);event={'review_required':'ai_research_portfolio_review_requested','accepted_for_research':'ai_research_portfolio_accepted','rejected':'ai_research_portfolio_rejected'}[new];self._obs(event,{'portfolio_id':str(p.id),'status':new});return p
    def _obs(self,event,ctx):
        try:ResearchObservationService(self.db).record(ObservationCreate(event_type=event,source='ai_matching',context=ctx))
        except Exception:self.db.rollback()

class ProfileRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID; source_type:str; blueprint_id:UUID|None; variant_id:UUID|None; profile_version:str; symbol_scope:list[Any]; timeframe_scope:list[Any]; regime:str; validation_ids:list[Any]; sample_size:int; simulated_trade_count:int; expectancy:Decimal; profit_factor:Decimal; win_rate:Decimal; max_drawdown:Decimal; stability_score:Decimal; data_quality_score:Decimal; overfit_risk_score:Decimal; execution_cost_drag:Decimal; regime_score:Decimal; compatibility_score:Decimal; strengths:list[Any]; weaknesses:list[Any]; warnings:list[Any]; configuration:dict[str,Any]; configuration_hash:str; created_at:datetime; updated_at:datetime

class PortfolioRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID; name:str; portfolio_version:str; portfolio_type:str; status:str; symbol_scope:list[Any]; timeframe_scope:list[Any]; regime_scope:list[Any]; source_profile_ids:list[Any]; source_blueprint_ids:list[Any]; source_variant_ids:list[Any]; source_validation_ids:list[Any]; component_count:int; allocation_method:str; allocation_weights:dict[str,Any]; expected_metrics:dict[str,Any]; diversification_metrics:dict[str,Any]; correlation_metrics:dict[str,Any]; concentration_score:Decimal; robustness_score:Decimal; data_quality_score:Decimal; readiness_score:Decimal; warnings:list[Any]; blocking_reasons:list[Any]; configuration:dict[str,Any]; configuration_hash:str; created_at:datetime; updated_at:datetime
