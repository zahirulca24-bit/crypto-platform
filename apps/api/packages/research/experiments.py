from __future__ import annotations
import hashlib, json, uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models import ResearchExperiment, ResearchHypothesis, ResearchObservation, TradeOutcome, MarketFeatureSnapshot

EXPERIMENT_VERSION='1.0.0'
EXPERIMENT_TYPES={'historical_replay','hypothesis_validation','parameter_comparison','regime_validation','feature_filter_validation','execution_quality_validation'}
D=Decimal

DEFAULT_CONFIG={
    'validation_ratio':'0.30','minimum_sample_size':5,'minimum_profit_factor':'1.00',
    'maximum_drawdown':'1000000','minimum_stability':'0.35','minimum_data_quality':'0.45',
    'require_positive_expectancy':True,
}

class ExperimentRunRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    hypothesis_id: uuid.UUID
    experiment_type: str='hypothesis_validation'
    start: datetime|None=None
    end: datetime|None=None
    validation_ratio: Decimal=Field(default=Decimal('0.30'),ge=0,lt=1)
    minimum_sample_size: int=Field(default=5,ge=1,le=100000)
    minimum_profit_factor: Decimal=Field(default=Decimal('1.00'),ge=0)
    maximum_drawdown: Decimal=Field(default=Decimal('1000000'),ge=0)
    minimum_stability: Decimal=Field(default=Decimal('0.35'),ge=0,le=1)
    minimum_data_quality: Decimal=Field(default=Decimal('0.45'),ge=0,le=1)
    require_positive_expectancy: bool=True

class ExperimentRead(BaseModel):
    id:uuid.UUID; hypothesis_id:uuid.UUID; start_observation_event_id:uuid.UUID|None; completion_observation_event_id:uuid.UUID|None; experiment_type:str; status:str
    symbol:str|None; timeframe:str|None; strategy_name:str|None; strategy_version:str|None
    train_start:datetime; train_end:datetime; validation_start:datetime|None; validation_end:datetime|None
    configuration:dict[str,Any]; configuration_hash:str; experiment_version:str; hypothesis_version:str; hypothesis_configuration_hash:str
    sample_size:int; baseline_sample_size:int; result_metrics:dict[str,Any]; baseline_metrics:dict[str,Any]; comparison_metrics:dict[str,Any]
    score:Decimal; stability_score:Decimal; data_quality_score:Decimal; passed:bool; failure_reasons:list[Any]
    started_at:datetime; completed_at:datetime|None; created_at:datetime

class ExperimentComparison(BaseModel):
    experiment_id:uuid.UUID; hypothesis_id:uuid.UUID; candidate_parameters:dict[str,Any]; baseline_parameters:dict[str,Any]
    result_metrics:dict[str,Any]; baseline_metrics:dict[str,Any]; comparison_metrics:dict[str,Any]
    train_metrics:dict[str,Any]; validation_metrics:dict[str,Any]


def canonical_hash(payload:dict[str,Any])->str:
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True,default=str).encode()).hexdigest()
def q(v:Decimal)->Decimal: return v.quantize(D('0.000001'),rounding=ROUND_HALF_UP)
def clamp(v:Decimal)->Decimal: return max(D('0'),min(D('1'),v))
def dec(v)->Decimal: return D(str(v or 0))

def metrics(rows:list[TradeOutcome])->dict[str,Any]:
    n=len(rows); wins=[r for r in rows if dec(r.net_pnl)>0]; losses=[r for r in rows if dec(r.net_pnl)<0]
    net=sum((dec(r.net_pnl) for r in rows),D('0')); gross=sum((dec(r.gross_pnl) for r in rows),D('0'))
    gp=sum((dec(r.net_pnl) for r in wins),D('0')); gl=abs(sum((dec(r.net_pnl) for r in losses),D('0')))
    pf=(gp/gl if gl else (D('999') if gp>0 else D('0')))
    expectancy=net/D(n) if n else D('0')
    rs=[dec(r.r_multiple) for r in rows if r.r_multiple is not None]
    equity=D('0'); peak=D('0'); max_dd=D('0')
    for r in rows:
        equity+=dec(r.net_pnl); peak=max(peak,equity); max_dd=max(max_dd,peak-equity)
    result={
        'trade_count':n,'wins':len(wins),'losses':len(losses),'win_rate':str(q(D(len(wins))/D(n) if n else D('0'))),
        'net_pnl':str(q(net)),'gross_pnl':str(q(gross)),'expectancy':str(q(expectancy)),'profit_factor':str(q(pf)),
        'average_r_multiple':str(q(sum(rs,D('0'))/D(len(rs)))) if rs else None,
        'average_mae':str(q(sum((dec(r.mae) for r in rows),D('0'))/D(n))) if n else '0.000000',
        'average_mfe':str(q(sum((dec(r.mfe) for r in rows),D('0'))/D(n))) if n else '0.000000',
        'max_drawdown':str(q(max_dd)),'fees':str(q(sum((dec(r.fees) for r in rows),D('0')))),
        'slippage':str(q(sum((dec(r.slippage) for r in rows),D('0')))),
        'average_holding_time':str(q(sum((dec(r.holding_time_seconds) for r in rows),D('0'))/D(n))) if n else '0.000000',
    }
    return result

def comparison(candidate:dict,baseline:dict)->dict[str,Any]:
    keys=['win_rate','net_pnl','expectancy','profit_factor','average_r_multiple','average_mae','average_mfe','max_drawdown','fees','slippage','average_holding_time']
    out={}
    for k in keys:
        if candidate.get(k) is None or baseline.get(k) is None: out[f'{k}_difference']=None
        else: out[f'{k}_difference']=str(q(dec(candidate[k])-dec(baseline[k])))
    return out

def experiment_score(m:dict,base:dict,sample:int,minimum:int,stability:Decimal,cost_ratio:Decimal)->Decimal:
    improvement=(dec(m['expectancy'])-dec(base['expectancy']))/max(abs(dec(base['expectancy'])),D('1'))
    perf=clamp((improvement+D('1'))/D('2'))
    exp=clamp((dec(m['expectancy'])+D('10'))/D('20'))
    pf=clamp(dec(m['profit_factor'])/D('2'))
    draw=clamp(D('1')-(dec(m['max_drawdown'])/(abs(dec(m['net_pnl']))+dec(m['max_drawdown'])+D('1'))))
    sample_factor=min(D('1'),D(sample)/D(max(minimum,1)))
    cost=clamp(D('1')-cost_ratio)
    return q(clamp(perf*D('.25')+exp*D('.15')+pf*D('.15')+draw*D('.15')+sample_factor*D('.10')+stability*D('.15')+cost*D('.05')))

def stability_score(train:dict,val:dict|None,segments:list[dict])->Decimal:
    components=[]
    if val and val.get('trade_count',0):
        t=dec(train['expectancy']); v=dec(val['expectancy']); components.append(clamp(D('1')-abs(t-v)/(abs(t)+abs(v)+D('1'))))
        components.append(D('1') if (t>=0)==(v>=0) else D('0'))
    exps=[dec(s['expectancy']) for s in segments if s.get('trade_count',0)]
    if len(exps)>1:
        mean=sum(exps,D('0'))/D(len(exps)); dispersion=sum((abs(x-mean) for x in exps),D('0'))/D(len(exps))
        components.append(clamp(D('1')-dispersion/(abs(mean)+dispersion+D('1'))))
    return q(sum(components,D('0'))/D(len(components))) if components else D('0.500000')

def data_quality_score(rows:list[TradeOutcome],minimum:int)->Decimal:
    if not rows:return D('0.000000')
    sample=min(D('1'),D(len(rows))/D(max(minimum,1)))
    feat=D(sum(1 for r in rows if r.entry_feature_snapshot_id is not None))/D(len(rows))
    regime=D(sum(1 for r in rows if r.regime_at_entry is not None))/D(len(rows))
    execution=D(sum(1 for r in rows if r.fees is not None and r.slippage is not None))/D(len(rows))
    context=D(sum(1 for r in rows if r.context is not None))/D(len(rows))
    return q(clamp(sample*D('.30')+feat*D('.20')+regime*D('.20')+execution*D('.20')+context*D('.10')))

class ResearchExperimentService:
    """Historical research evaluator. Contains no exchange/trading/runtime dependencies."""
    def __init__(self,db:Session): self.db=db

    def run(self,r:ExperimentRunRequest)->ExperimentRead:
        if r.experiment_type not in EXPERIMENT_TYPES: raise ValueError('Unsupported experiment type')
        h=self.db.get(ResearchHypothesis,r.hypothesis_id)
        if h is None: raise LookupError('Research hypothesis not found')
        rows=self._scope(h,r)
        if not rows: raise ValueError('No persisted historical trade outcomes in scope')
        split=self._split(rows,r.validation_ratio)
        train,val=split
        train_start=train[0].entry_time; train_end=max(x.exit_time for x in train)
        val_start=val[0].entry_time if val else None; val_end=val[-1].entry_time if val else None
        config={**DEFAULT_CONFIG,'validation_ratio':str(r.validation_ratio),'minimum_sample_size':r.minimum_sample_size,
                'minimum_profit_factor':str(r.minimum_profit_factor),'maximum_drawdown':str(r.maximum_drawdown),
                'minimum_stability':str(r.minimum_stability),'minimum_data_quality':str(r.minimum_data_quality),
                'require_positive_expectancy':r.require_positive_expectancy,
                'hypothesis_version':h.hypothesis_version,'hypothesis_configuration_hash':h.configuration_hash,
                'scope_start':rows[0].entry_time.isoformat(),'scope_end':rows[-1].entry_time.isoformat(),
                'evidence_outcome_ids':[str(x.id) for x in rows],
                'train_start':train_start.isoformat(),'train_end':train_end.isoformat(),
                'validation_start':val_start.isoformat() if val_start else None,'validation_end':val_end.isoformat() if val_end else None}
        ch=canonical_hash(config)
        existing=self.db.execute(select(ResearchExperiment).where(ResearchExperiment.hypothesis_id==h.id,ResearchExperiment.experiment_type==r.experiment_type,ResearchExperiment.experiment_version==EXPERIMENT_VERSION,ResearchExperiment.configuration_hash==ch)).scalar_one_or_none()
        if existing:return self._read(existing)
        started=datetime.now(timezone.utc)
        row=ResearchExperiment(hypothesis_id=h.id,experiment_type=r.experiment_type,status='running',symbol=h.symbol,timeframe=h.timeframe,
            strategy_name=h.strategy_name,strategy_version=h.strategy_version,train_start=train_start,train_end=train_end,validation_start=val_start,validation_end=val_end,
            configuration=config,configuration_hash=ch,experiment_version=EXPERIMENT_VERSION,hypothesis_version=h.hypothesis_version,hypothesis_configuration_hash=h.configuration_hash,
            sample_size=0,baseline_sample_size=len(rows),result_metrics={},baseline_metrics={},comparison_metrics={},score=D('0'),stability_score=D('0'),data_quality_score=D('0'),passed=False,failure_reasons=[],started_at=started)
        self.db.add(row); self.db.commit(); self.db.refresh(row)
        self._observe(row,h,'experiment_started',{'sample_size':0,'score':'0.000000','stability_score':'0.000000','data_quality_score':'0.000000','passed':False,'failure_reasons':[],'historical_scope':{'start':config['scope_start'],'end':config['scope_end']}} ,start=True)
        if h.status=='queued':
            h.status='testing'; h.updated_at=datetime.now(timezone.utc); self.db.commit()
            status_obs=ResearchObservation(event_type='hypothesis_status_changed',source='research.experiments',symbol=h.symbol,timeframe=h.timeframe,strategy_name=h.strategy_name,strategy_version=h.strategy_version,context={'hypothesis_id':str(h.id),'hypothesis_type':h.hypothesis_type,'confidence':str(h.confidence_score),'priority':str(h.priority_score),'status':'testing','reason':'experiment_started'})
            self.db.add(status_obs); self.db.commit()
        candidate=[x for x in rows if self._matches(h,x,r.experiment_type)]
        baseline=rows
        result_m=metrics(candidate); base_m=metrics(baseline); comp=comparison(result_m,base_m)
        train_candidate=[x for x in train if x in candidate]; val_candidate=[x for x in val if x in candidate]
        train_m=metrics(train_candidate); val_m=metrics(val_candidate) if val else {}
        segment_metrics=[]
        for attr in ('symbol','regime_at_entry'):
            buckets={}
            for x in candidate:buckets.setdefault(str(getattr(x,attr) or 'unknown'),[]).append(x)
            segment_metrics += [metrics(v) for _,v in sorted(buckets.items())]
        stability=stability_score(train_m,val_m if val else None,segment_metrics)
        quality=data_quality_score(candidate,r.minimum_sample_size)
        costs=dec(result_m['fees'])+abs(dec(result_m['slippage'])); gross_abs=sum((abs(dec(x.gross_pnl)) for x in candidate),D('0')); cost_ratio=costs/(gross_abs+D('1'))
        score=experiment_score(result_m,base_m,len(candidate),r.minimum_sample_size,stability,cost_ratio)
        failures=[]
        if len(candidate)<r.minimum_sample_size: failures.append({'code':'minimum_sample_size','actual':len(candidate),'required':r.minimum_sample_size})
        if r.require_positive_expectancy and dec(result_m['expectancy'])<=0: failures.append({'code':'positive_expectancy','actual':result_m['expectancy']})
        if dec(result_m['max_drawdown'])>r.maximum_drawdown: failures.append({'code':'maximum_drawdown','actual':result_m['max_drawdown'],'maximum':str(r.maximum_drawdown)})
        if dec(result_m['profit_factor'])<r.minimum_profit_factor: failures.append({'code':'minimum_profit_factor','actual':result_m['profit_factor'],'minimum':str(r.minimum_profit_factor)})
        if stability<r.minimum_stability: failures.append({'code':'minimum_stability','actual':str(stability),'minimum':str(r.minimum_stability)})
        if quality<r.minimum_data_quality: failures.append({'code':'minimum_data_quality','actual':str(quality),'minimum':str(r.minimum_data_quality)})
        row.sample_size=len(candidate); row.result_metrics={**result_m,'train':train_m,'validation':val_m}; row.baseline_metrics=base_m
        row.comparison_metrics={**comp,'candidate_parameters':self._candidate_parameters(h),'baseline_parameters':self._baseline_parameters(h),
            'chronological':True,'train_validation_overlap':False}
        row.score=score; row.stability_score=stability; row.data_quality_score=quality; row.passed=not failures; row.failure_reasons=failures; row.status='completed'; row.completed_at=datetime.now(timezone.utc)
        self.db.commit(); self.db.refresh(row)
        self._observe(row,h,'experiment_completed',{'sample_size':row.sample_size,'score':str(score),'stability_score':str(stability),'data_quality_score':str(quality),'passed':row.passed,'failure_reasons':failures,'historical_scope':{'start':config['scope_start'],'end':config['scope_end']}},start=False)
        self.db.refresh(row); return self._read(row)

    def _scope(self,h,r):
        s=select(TradeOutcome)
        if h.symbol:s=s.where(TradeOutcome.symbol==h.symbol)
        if h.timeframe:s=s.where(TradeOutcome.timeframe==h.timeframe)
        if h.strategy_name:s=s.where(TradeOutcome.strategy_name==h.strategy_name)
        if h.strategy_version:s=s.where(TradeOutcome.strategy_version==h.strategy_version)
        if r.start:s=s.where(TradeOutcome.entry_time>=r.start)
        if r.end:s=s.where(TradeOutcome.exit_time<=r.end)
        return self.db.execute(s.order_by(TradeOutcome.entry_time.asc(),TradeOutcome.id.asc())).scalars().all()
    @staticmethod
    def _split(rows,ratio):
        if not rows:return [],[]
        if ratio<=0 or len(rows)<2:return rows,[]
        val_n=max(1,int(len(rows)*float(ratio))); val_n=min(val_n,len(rows)-1)
        validation=rows[-val_n:]; cut=validation[0].entry_time
        training=[x for x in rows[:-val_n] if x.exit_time < cut]
        if not training: raise ValueError('Unable to create non-overlapping chronological train/validation windows')
        return training,validation
    def _matches(self,h,o,experiment_type):
        if h.regime and o.regime_at_entry!=h.regime:return False
        if h.exit_conditions.get('exit_reason') and o.exit_reason!=h.exit_conditions['exit_reason']:return False
        cond={**(h.feature_conditions or {}),**(h.entry_conditions or {})}
        if cond and o.entry_feature_snapshot_id:
            f=self.db.get(MarketFeatureSnapshot,o.entry_feature_snapshot_id)
            if f is None or f.candle_open_time > o.entry_time:return False
            if 'rsi_gte' in cond and (f.rsi is None or dec(f.rsi)<dec(cond['rsi_gte'])):return False
            if 'rsi_lt' in cond and (f.rsi is None or dec(f.rsi)>=dec(cond['rsi_lt'])):return False
        elif cond:return False
        if h.risk_conditions.get('r_multiple_lt') is not None and (o.r_multiple is None or dec(o.r_multiple)>=dec(h.risk_conditions['r_multiple_lt'])):return False
        # Execution-quality hypotheses evaluate the same historical scope because their candidate is cost quality itself.
        return True
    @staticmethod
    def _candidate_parameters(h): return {'feature_conditions':h.feature_conditions or {},'entry_conditions':h.entry_conditions or {},'exit_conditions':h.exit_conditions or {},'risk_conditions':h.risk_conditions or {}}
    @staticmethod
    def _baseline_parameters(h):
        if h.hypothesis_type=='parameter_candidate' and ('rsi_gte' in (h.entry_conditions or {})): return {'rsi_gte':'baseline_unfiltered'}
        return {'scope':'unfiltered_historical_baseline'}
    def get(self,eid):
        x=self.db.get(ResearchExperiment,eid); return self._read(x) if x else None
    def comparison(self,eid):
        x=self.db.get(ResearchExperiment,eid)
        if not x:return None
        return ExperimentComparison(experiment_id=x.id,hypothesis_id=x.hypothesis_id,candidate_parameters=x.comparison_metrics.get('candidate_parameters',{}),baseline_parameters=x.comparison_metrics.get('baseline_parameters',{}),result_metrics=x.result_metrics,baseline_metrics=x.baseline_metrics,comparison_metrics=x.comparison_metrics,train_metrics=x.result_metrics.get('train',{}),validation_metrics=x.result_metrics.get('validation',{}))
    def list(self,*,hypothesis_id=None,experiment_type=None,status=None,strategy=None,symbol=None,timeframe=None,passed=None,start=None,end=None,minimum_score=None,limit=100,offset=0):
        s=select(ResearchExperiment)
        if hypothesis_id:s=s.where(ResearchExperiment.hypothesis_id==hypothesis_id)
        if experiment_type:s=s.where(ResearchExperiment.experiment_type==experiment_type)
        if status:s=s.where(ResearchExperiment.status==status)
        if strategy:s=s.where(ResearchExperiment.strategy_name==strategy)
        if symbol:s=s.where(ResearchExperiment.symbol==symbol.upper())
        if timeframe:s=s.where(ResearchExperiment.timeframe==timeframe)
        if passed is not None:s=s.where(ResearchExperiment.passed==passed)
        if start:s=s.where(ResearchExperiment.created_at>=start)
        if end:s=s.where(ResearchExperiment.created_at<=end)
        if minimum_score is not None:s=s.where(ResearchExperiment.score>=minimum_score)
        rows=self.db.execute(s.order_by(ResearchExperiment.created_at.desc(),ResearchExperiment.id.desc()).offset(offset).limit(limit)).scalars().all()
        return [self._read(x) for x in rows]
    def _observe(self,row,h,event_type,extra,start):
        obs=ResearchObservation(event_type=event_type,source='research.experiments',symbol=row.symbol,timeframe=row.timeframe,strategy_name=row.strategy_name,strategy_version=row.strategy_version,
            context={'experiment_id':str(row.id),'hypothesis_id':str(h.id),'experiment_type':row.experiment_type,**extra})
        self.db.add(obs); self.db.commit(); self.db.refresh(obs)
        if start: row.start_observation_event_id=obs.event_id
        else: row.completion_observation_event_id=obs.event_id
        self.db.commit()
    @staticmethod
    def _read(row): return ExperimentRead.model_validate({k:getattr(row,k) for k in ExperimentRead.model_fields})
