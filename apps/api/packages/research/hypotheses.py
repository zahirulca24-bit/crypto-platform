from __future__ import annotations
import hashlib, json, uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models import TradeOutcome, MarketFeatureSnapshot, ResearchHypothesis, ResearchObservation

HYPOTHESIS_VERSION='1.0.0'
HYPOTHESIS_TYPES={'regime_performance','symbol_performance','feature_condition','strategy_filter','exit_behavior','risk_behavior','execution_quality','parameter_candidate'}
STATUSES={'proposed','queued','testing','validated','rejected','archived'}
D=Decimal

class HypothesisGenerateRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    strategy: str|None=None; symbol: str|None=None; timeframe: str|None=None
    start: datetime|None=None; end: datetime|None=None
    minimum_sample: int=Field(default=5,ge=1,le=10000)
    hypothesis_types: list[str]|None=None

class StatusPatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status: str

class HypothesisRead(BaseModel):
    id: uuid.UUID; hypothesis_type:str; title:str; description:str; status:str
    strategy_name:str|None; strategy_version:str|None; symbol:str|None; timeframe:str|None; regime:str|None
    feature_conditions:dict[str,Any]; entry_conditions:dict[str,Any]; exit_conditions:dict[str,Any]; risk_conditions:dict[str,Any]
    evidence_summary:dict[str,Any]; source_metrics:dict[str,Any]; sample_size:int
    confidence_score:Decimal; priority_score:Decimal; hypothesis_version:str; configuration:dict[str,Any]; configuration_hash:str
    parent_hypothesis_id:uuid.UUID|None; observation_event_id:uuid.UUID|None; created_at:datetime; updated_at:datetime

def canonical_hash(payload:dict[str,Any])->str:
    raw=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True,default=str)
    return hashlib.sha256(raw.encode()).hexdigest()

def q(v:Decimal)->Decimal: return v.quantize(D('0.000001'),rounding=ROUND_HALF_UP)
def clamp(v:Decimal)->Decimal: return max(D('0'),min(D('1'),v))

def confidence_score(sample:int, minimum:int, effect:Decimal, consistency:Decimal, quality:Decimal)->Decimal:
    sample_factor=min(D('1'),D(sample)/D(max(minimum,1)))
    effect_factor=min(D('1'),abs(effect))
    # Small samples are deliberately capped by sample_factor; not a p-value/probability.
    return q(clamp(sample_factor*D('.35')+effect_factor*D('.30')+clamp(consistency)*D('.20')+clamp(quality)*D('.15')))

def priority_score(confidence:Decimal,effect:Decimal,sample:int,minimum:int,economic:Decimal,frequency:Decimal)->Decimal:
    sample_factor=min(D('1'),D(sample)/D(max(minimum,1)))
    return q(clamp(confidence*D('.30')+min(D('1'),abs(effect))*D('.25')+sample_factor*D('.15')+min(D('1'),abs(economic))*D('.20')+clamp(frequency)*D('.10')))

class ResearchHypothesisService:
    """Read/analytics-only hypothesis engine; deliberately has no trading/runtime dependencies."""
    def __init__(self,db:Session): self.db=db

    def generate(self,r:HypothesisGenerateRequest)->list[HypothesisRead]:
        types=set(r.hypothesis_types or HYPOTHESIS_TYPES)
        bad=types-HYPOTHESIS_TYPES
        if bad: raise ValueError(f'Unsupported hypothesis types: {sorted(bad)}')
        outcomes=self._outcomes(r)
        if not outcomes: return []
        candidates=[]
        if 'regime_performance' in types: candidates += self._comparative(outcomes,'regime_at_entry','regime_performance',r)
        if 'symbol_performance' in types: candidates += self._comparative(outcomes,'symbol','symbol_performance',r)
        if 'strategy_filter' in types: candidates += self._comparative(outcomes,'strategy_name','strategy_filter',r)
        if 'exit_behavior' in types: candidates += self._exit(outcomes,r)
        if 'execution_quality' in types: candidates += self._execution(outcomes,r)
        if 'risk_behavior' in types: candidates += self._risk(outcomes,r)
        if 'feature_condition' in types: candidates += self._features(outcomes,r,False)
        if 'parameter_candidate' in types: candidates += self._features(outcomes,r,True)
        return [self._persist(c,r,outcomes) for c in candidates]

    def _outcomes(self,r):
        s=select(TradeOutcome)
        if r.strategy: s=s.where(TradeOutcome.strategy_name==r.strategy)
        if r.symbol: s=s.where(TradeOutcome.symbol==r.symbol.upper())
        if r.timeframe: s=s.where(TradeOutcome.timeframe==r.timeframe)
        if r.start: s=s.where(TradeOutcome.entry_time>=r.start)
        if r.end: s=s.where(TradeOutcome.exit_time<=r.end)
        return self.db.execute(s.order_by(TradeOutcome.entry_time,TradeOutcome.id)).scalars().all()

    @staticmethod
    def _stats(rows):
        n=len(rows); net=sum((D(str(x.net_pnl)) for x in rows),D('0')); wins=sum(1 for x in rows if x.net_pnl>0)
        gross=sum((D(str(x.gross_pnl)) for x in rows),D('0')); fees=sum((D(str(x.fees)) for x in rows),D('0')); slip=sum((D(str(x.slippage)) for x in rows),D('0'))
        return {'sample_size':n,'net_pnl':net,'gross_pnl':gross,'avg_net_pnl':net/D(n) if n else D('0'),'win_rate':D(wins)/D(n) if n else D('0'),'fees':fees,'slippage':slip}

    def _comparative(self,rows,field,kind,r):
        groups={}
        for x in rows:
            key=getattr(x,field) or 'unknown'; groups.setdefault(str(key),[]).append(x)
        if len(groups)<2: return []
        ranked=sorted(((self._stats(v)['avg_net_pnl'],k,v) for k,v in groups.items()),reverse=True,key=lambda z:(z[0],z[1]))
        best_avg,best,brows=ranked[0]; base_rows=[x for k,v in groups.items() if k!=best for x in v]; base=self._stats(base_rows); st=self._stats(brows)
        denom=max(abs(base['avg_net_pnl']),D('1')); effect=(best_avg-base['avg_net_pnl'])/denom
        return [self._candidate(kind, f'{kind.replace("_"," ").title()}: {best}',
            f'Observed association: {best} has higher average net outcome than the comparison baseline; candidate hypothesis requires validation.',
            st,base,effect,r, extra={'group_field':field,'group_value':best}, regime=best if field=='regime_at_entry' else None,
            symbol=best if field=='symbol' else None, strategy=best if field=='strategy_name' else None)]

    def _exit(self,rows,r):
        losses=[x for x in rows if x.net_pnl<0]
        if not losses:return []
        counts={}
        for x in losses: counts[x.exit_reason]=counts.get(x.exit_reason,0)+1
        reason,count=max(counts.items(),key=lambda kv:(kv[1],kv[0])); st=self._stats([x for x in losses if x.exit_reason==reason]); base=self._stats(losses)
        effect=D(count)/D(len(losses))
        return [self._candidate('exit_behavior',f'Loss exits concentrated in {reason}',f'Observed association: {reason} accounts for a large share of losing exits; requires validation.',st,base,effect,r,extra={'exit_reason':reason,'loss_share':str(effect)},exit_conditions={'exit_reason':reason})]

    def _execution(self,rows,r):
        st=self._stats(rows); drag=st['fees']+st['slippage']; gross_abs=sum((abs(D(str(x.gross_pnl))) for x in rows),D('0'))
        effect=drag/gross_abs if gross_abs else D('0')
        if drag<=0:return []
        return [self._candidate('execution_quality','Execution costs reduce observed gross edge','Observed association: persisted fees and slippage reduce gross trading edge; requires validation.',st,st,effect,r,extra={'cost_drag':str(drag),'gross_abs':str(gross_abs)})]

    def _risk(self,rows,r):
        with_r=[x for x in rows if x.r_multiple is not None]
        if not with_r:return []
        neg=[x for x in with_r if x.r_multiple<0]; st=self._stats(neg or with_r); base=self._stats(with_r); effect=D(len(neg))/D(len(with_r))
        return [self._candidate('risk_behavior','Negative R outcomes warrant risk-filter review','Observed association: negative R-multiple outcomes occur in the evidence window; candidate risk hypothesis requires validation.',st,base,effect,r,extra={'negative_r_count':len(neg)},risk_conditions={'r_multiple_lt':'0'})]

    def _features(self,rows,r,param):
        pairs=[]
        for x in rows:
            if x.entry_feature_snapshot_id:
                f=self.db.get(MarketFeatureSnapshot,x.entry_feature_snapshot_id)
                if f and f.rsi is not None: pairs.append((x,f))
        if len(pairs)<2:return []
        good=[x for x,f in pairs if D(str(f.rsi))>=D('50')]
        bad=[x for x,f in pairs if D(str(f.rsi))<D('50')]
        if not good or not bad:return []
        gs,bs=self._stats(good),self._stats(bad); effect=(gs['avg_net_pnl']-bs['avg_net_pnl'])/max(abs(bs['avg_net_pnl']),D('1'))
        kind='parameter_candidate' if param else 'feature_condition'
        cond={'rsi_gte':'50'}
        title='Candidate RSI threshold parameter' if param else 'RSI feature condition association'
        return [self._candidate(kind,title,'Observed association: outcomes differ across a deterministic RSI threshold; candidate hypothesis requires replay validation.',gs,bs,effect,r,extra={'threshold':'50','feature':'rsi'},feature_conditions=cond,entry_conditions=cond)]

    def _candidate(self,kind,title,desc,st,base,effect,r,extra=None,regime=None,symbol=None,strategy=None,feature_conditions=None,entry_conditions=None,exit_conditions=None,risk_conditions=None):
        n=st['sample_size']; consistency=abs(st['win_rate']-D('.5'))*2; quality=D('1') if n else D('0')
        conf=confidence_score(n,r.minimum_sample,effect,consistency,quality)
        economic=abs(st['net_pnl'])/max(abs(st['gross_pnl']),D('1')); freq=D(n)/D(max(len(self._outcomes(r)),1))
        pri=priority_score(conf,effect,n,r.minimum_sample,economic,freq)
        insufficient=n<r.minimum_sample
        evidence={'evidence_status':'insufficient' if insufficient else 'sufficient','observed_association':True,'causality_claimed':False,'requires_validation':True,'observed_difference':str(q(st['avg_net_pnl']-base['avg_net_pnl'])),'supporting_metrics':self._json_stats(st),'baseline':self._json_stats(base)}
        if extra:evidence.update(extra)
        return dict(hypothesis_type=kind,title=title,description=desc,status='proposed',strategy_name=strategy or r.strategy,strategy_version=None,symbol=symbol or (r.symbol.upper() if r.symbol else None),timeframe=r.timeframe,regime=regime,
          feature_conditions=feature_conditions or {},entry_conditions=entry_conditions or {},exit_conditions=exit_conditions or {},risk_conditions=risk_conditions or {},evidence_summary=evidence,source_metrics={'supporting':self._json_stats(st),'baseline':self._json_stats(base)},sample_size=n,confidence_score=conf,priority_score=pri)

    @staticmethod
    def _json_stats(st): return {k:(str(q(v)) if isinstance(v,Decimal) else v) for k,v in st.items()}

    def _persist(self,c,r,allrows):
        evidence_ids=[str(x.id) for x in allrows]
        config={'minimum_sample':r.minimum_sample,'strategy':r.strategy,'symbol':r.symbol.upper() if r.symbol else None,'timeframe':r.timeframe,'start':r.start.isoformat() if r.start else None,'end':r.end.isoformat() if r.end else None,'evidence_outcome_ids':evidence_ids,'rule':c['hypothesis_type']}
        h=canonical_hash(config)
        old=self.db.execute(select(ResearchHypothesis).where(ResearchHypothesis.hypothesis_type==c['hypothesis_type'],ResearchHypothesis.hypothesis_version==HYPOTHESIS_VERSION,ResearchHypothesis.configuration_hash==h)).scalar_one_or_none()
        if old:return self._read(old)
        row=ResearchHypothesis(**c,hypothesis_version=HYPOTHESIS_VERSION,configuration=config,configuration_hash=h)
        self.db.add(row)
        try:self.db.commit()
        except IntegrityError:
            self.db.rollback(); old=self.db.execute(select(ResearchHypothesis).where(ResearchHypothesis.hypothesis_type==c['hypothesis_type'],ResearchHypothesis.hypothesis_version==HYPOTHESIS_VERSION,ResearchHypothesis.configuration_hash==h)).scalar_one(); return self._read(old)
        self.db.refresh(row); self._observe(row,'hypothesis_proposed'); self.db.refresh(row); return self._read(row)

    def set_status(self,hid:uuid.UUID,status:str):
        if status not in STATUSES: raise ValueError('Unsupported hypothesis status')
        row=self.db.get(ResearchHypothesis,hid)
        if not row: raise LookupError('Research hypothesis not found')
        previous=row.status; row.status=status; row.updated_at=datetime.now(timezone.utc); self.db.commit(); self.db.refresh(row)
        self._observe(row,'hypothesis_status_changed',{'previous_status':previous,'status':status}); return self._read(row)

    def get(self,hid):
        row=self.db.get(ResearchHypothesis,hid); return self._read(row) if row else None
    def list(self,*,hypothesis_type=None,status=None,strategy=None,symbol=None,timeframe=None,regime=None,min_confidence=None,min_priority=None,start=None,end=None,limit=100,offset=0):
        s=select(ResearchHypothesis)
        for val,col in [(hypothesis_type,ResearchHypothesis.hypothesis_type),(status,ResearchHypothesis.status),(strategy,ResearchHypothesis.strategy_name),(timeframe,ResearchHypothesis.timeframe),(regime,ResearchHypothesis.regime)]:
            if val is not None:s=s.where(col==val)
        if symbol:s=s.where(ResearchHypothesis.symbol==symbol.upper())
        if min_confidence is not None:s=s.where(ResearchHypothesis.confidence_score>=min_confidence)
        if min_priority is not None:s=s.where(ResearchHypothesis.priority_score>=min_priority)
        if start:s=s.where(ResearchHypothesis.created_at>=start)
        if end:s=s.where(ResearchHypothesis.created_at<=end)
        rows=self.db.execute(s.order_by(ResearchHypothesis.created_at.desc(),ResearchHypothesis.id.desc()).offset(offset).limit(limit)).scalars().all(); return [self._read(x) for x in rows]

    def _observe(self,row,event_type,extra=None):
        obs=ResearchObservation(event_type=event_type,source='research.hypotheses',symbol=row.symbol,timeframe=row.timeframe,strategy_name=row.strategy_name,strategy_version=row.strategy_version,
            context={'hypothesis_id':str(row.id),'hypothesis_type':row.hypothesis_type,'confidence':str(row.confidence_score),'priority':str(row.priority_score),'status':row.status,'evidence_scope':row.configuration,**(extra or {})})
        self.db.add(obs); self.db.commit(); self.db.refresh(obs); row.observation_event_id=obs.event_id; self.db.commit()

    @staticmethod
    def _read(row):
        return HypothesisRead.model_validate({k:getattr(row,k) for k in HypothesisRead.model_fields})
