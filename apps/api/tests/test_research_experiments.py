from datetime import datetime,timedelta,timezone
from decimal import Decimal
from uuid import uuid4
import inspect
import pytest
from sqlalchemy import create_engine,func,select
from sqlalchemy.orm import sessionmaker
from database import Base
from models import MarketFeatureSnapshot,ResearchExperiment,ResearchHypothesis,ResearchObservation,TradeOutcome
from packages.research.experiments import EXPERIMENT_VERSION,ExperimentRunRequest,ResearchExperimentService,canonical_hash,data_quality_score,experiment_score,stability_score,metrics

D=Decimal
@pytest.fixture
def edb(tmp_path):
    e=create_engine(f"sqlite:///{tmp_path/'experiments.db'}"); Base.metadata.create_all(e); S=sessionmaker(bind=e); db=S()
    try: yield db
    finally: db.close();e.dispose()

def seed(edb,n=12,kind='parameter_candidate',status='queued'):
    base=datetime(2026,8,1,tzinfo=timezone.utc); rows=[]
    for i in range(n):
        fid=uuid4(); rsi=D('60') if i%2==0 else D('40')
        edb.add(MarketFeatureSnapshot(id=fid,candle_id=uuid4(),exchange='demo',symbol='BTC/USDT',timeframe='1h',candle_open_time=base+timedelta(hours=i),feature_version='1.0.0',configuration={},configuration_hash=f'{i+1:064x}',rsi=rsi))
        positive=(i%2==0); net=D('12') if positive else D('-6')
        row=TradeOutcome(source_position_id=uuid4(),exchange='demo',symbol='BTC/USDT',timeframe='1h',strategy_name='alpha',strategy_version='1.0',strategy_config_hash='a'*64,side='long',entry_time=base+timedelta(hours=i),exit_time=base+timedelta(hours=i,minutes=30),entry_price=D('100'),exit_price=D('101'),quantity=D('1'),notional=D('100'),gross_pnl=net+D('2'),net_pnl=net,fees=D('1'),slippage=D('.5'),holding_time_seconds=D('1800'),exit_reason='take_profit' if positive else 'stop_loss',mae=D('2'),mfe=D('5'),return_pct=net/100,risk_amount=D('10'),r_multiple=net/10,regime_at_entry='trending_bull' if i<8 else 'ranging',entry_feature_snapshot_id=fid,outcome_version='1.0.0',context={'execution':'complete'})
        edb.add(row);rows.append(row)
    h=ResearchHypothesis(hypothesis_type=kind,title='candidate',description='observed association; requires validation',status=status,strategy_name='alpha',strategy_version='1.0',symbol='BTC/USDT',timeframe='1h',regime='trending_bull' if kind=='regime_performance' else None,feature_conditions={'rsi_gte':'50'} if kind in {'parameter_candidate','feature_condition'} else {},entry_conditions={'rsi_gte':'50'} if kind in {'parameter_candidate','feature_condition'} else {},exit_conditions={},risk_conditions={},evidence_summary={},source_metrics={},sample_size=n,confidence_score=D('.6'),priority_score=D('.7'),hypothesis_version='1.0.0',configuration={},configuration_hash='b'*64)
    edb.add(h);edb.commit();return h,rows

def run(edb,kind='parameter_candidate',**kwargs):
    h,rows=seed(edb,kind=kind); req=ExperimentRunRequest(hypothesis_id=h.id,experiment_type={'parameter_candidate':'parameter_comparison','regime_performance':'regime_validation','feature_condition':'feature_filter_validation'}.get(kind,'hypothesis_validation'),**kwargs); return h,rows,ResearchExperimentService(edb).run(req)

def test_chronological_replay(edb):
    _,rows,x=run(edb); ids=x.configuration['evidence_outcome_ids']; expected=[str(r.id) for r in sorted(rows,key=lambda z:(z.entry_time,str(z.id)))]; assert ids==expected

def test_no_future_leakage_scope_end(edb):
    h,rows=seed(edb); end=rows[7].exit_time; x=ResearchExperimentService(edb).run(ExperimentRunRequest(hypothesis_id=h.id,experiment_type='parameter_comparison',end=end)); assert all(edb.get(TradeOutcome,__import__('uuid').UUID(i)).exit_time<=end for i in x.configuration['evidence_outcome_ids'])

def test_chronological_train_validation_split(edb):
    _,_,x=run(edb); assert x.validation_start is not None and x.train_end < x.validation_start

def test_no_train_validation_overlap(edb):
    _,_,x=run(edb); assert x.comparison_metrics['train_validation_overlap'] is False and x.train_end<x.validation_start

def test_hypothesis_evaluation(edb):
    _,_,x=run(edb); assert x.sample_size>0 and int(x.result_metrics['trade_count'])==x.sample_size

def test_baseline_comparison(edb):
    _,_,x=run(edb); assert x.baseline_sample_size>=x.sample_size and 'expectancy_difference' in x.comparison_metrics

def test_parameter_comparison(edb):
    _,_,x=run(edb); assert x.experiment_type=='parameter_comparison' and x.comparison_metrics['candidate_parameters']['entry_conditions']['rsi_gte']=='50'

def test_regime_validation(edb):
    _,_,x=run(edb,'regime_performance'); assert x.experiment_type=='regime_validation' and x.sample_size==8

def test_feature_filter_validation(edb):
    _,_,x=run(edb,'feature_condition'); assert x.experiment_type=='feature_filter_validation' and x.sample_size==6

def test_deterministic_experiment_score():
    m={'expectancy':'2','profit_factor':'2','max_drawdown':'5','net_pnl':'20'};b={'expectancy':'1'}; a=experiment_score(m,b,10,5,D('.8'),D('.1')); assert a==experiment_score(m,b,10,5,D('.8'),D('.1')) and 0<=a<=1

def test_deterministic_stability_score():
    a={'trade_count':5,'expectancy':'2'};b={'trade_count':5,'expectancy':'1'}; assert stability_score(a,b,[a,b])==stability_score(a,b,[a,b])

def test_data_quality_score(edb):
    _,rows=seed(edb); assert D('0')<=data_quality_score(rows,5)<=D('1')

def test_small_sample_failure(edb):
    h,_=seed(edb,n=4); x=ResearchExperimentService(edb).run(ExperimentRunRequest(hypothesis_id=h.id,experiment_type='parameter_comparison',minimum_sample_size=10)); assert not x.passed and 'minimum_sample_size' in {r['code'] for r in x.failure_reasons}

def test_negative_expectancy_failure(edb):
    h,rows=seed(edb,n=6,kind='exit_behavior'); h.exit_conditions={'exit_reason':'stop_loss'};edb.commit(); x=ResearchExperimentService(edb).run(ExperimentRunRequest(hypothesis_id=h.id,minimum_sample_size=1)); assert 'positive_expectancy' in {r['code'] for r in x.failure_reasons}

def test_drawdown_gate(edb):
    h,_=seed(edb,kind='execution_quality'); x=ResearchExperimentService(edb).run(ExperimentRunRequest(hypothesis_id=h.id,experiment_type='execution_quality_validation',maximum_drawdown=D('0'),minimum_sample_size=1)); assert D(x.result_metrics['max_drawdown'])>0 and 'maximum_drawdown' in {r['code'] for r in x.failure_reasons}

def test_profit_factor_gate(edb):
    _,_,x=run(edb,minimum_profit_factor=D('1000')); assert 'minimum_profit_factor' in {r['code'] for r in x.failure_reasons}

def test_stability_gate(edb):
    h,rows=seed(edb); rows[-2].net_pnl=D('-30'); rows[-2].gross_pnl=D('-28'); edb.commit(); x=ResearchExperimentService(edb).run(ExperimentRunRequest(hypothesis_id=h.id,experiment_type='parameter_comparison',minimum_stability=D('.95'),minimum_sample_size=1)); assert x.stability_score<D('.95') and 'minimum_stability' in {r['code'] for r in x.failure_reasons}

def test_explicit_failure_reasons(edb):
    h,_=seed(edb,n=3); x=ResearchExperimentService(edb).run(ExperimentRunRequest(hypothesis_id=h.id,experiment_type='parameter_comparison',minimum_sample_size=100,minimum_profit_factor=D('1000'))); assert all('code' in r for r in x.failure_reasons) and len(x.failure_reasons)>=2

def test_deterministic_configuration_hash(): assert canonical_hash({'a':1,'b':2})==canonical_hash({'b':2,'a':1})

def test_experiment_idempotency(edb):
    h,_=seed(edb);svc=ResearchExperimentService(edb);req=ExperimentRunRequest(hypothesis_id=h.id,experiment_type='parameter_comparison');a=svc.run(req);b=svc.run(req);assert a.id==b.id and edb.scalar(select(func.count()).select_from(ResearchExperiment))==1

def test_experiment_retrieval_filtering(edb):
    h,_,x=run(edb);svc=ResearchExperimentService(edb);assert svc.get(x.id).id==x.id and len(svc.list(hypothesis_id=h.id,experiment_type='parameter_comparison',minimum_score=D('0')))==1

def test_comparison_endpoint_service(edb):
    _,_,x=run(edb); c=ResearchExperimentService(edb).comparison(x.id); assert c.experiment_id==x.id and c.train_metrics and c.validation_metrics

def test_research_observation_lifecycle_events(edb):
    _,_,x=run(edb); events=edb.execute(select(ResearchObservation).where(ResearchObservation.event_id.in_([x.start_observation_event_id,x.completion_observation_event_id]))).scalars().all(); assert {e.event_type for e in events}=={'experiment_started','experiment_completed'}

def test_hypothesis_testing_workflow(edb):
    h,_,_=run(edb);edb.refresh(h);assert h.status=='testing'

def test_production_strategy_config_unchanged(edb):
    h,_,_=run(edb);edb.refresh(h);assert h.configuration=={} and h.configuration_hash=='b'*64

def test_cannot_submit_trading_orders():
    forbidden={'place_order','submit_order','execute_order','create_demo_trade','promote_strategy'};assert set(dir(ResearchExperimentService)).isdisjoint(forbidden); import packages.research.experiments as m;src=inspect.getsource(m);assert 'ccxt' not in src and 'OpenAI' not in src and 'Gemini' not in src

def test_cannot_modify_positions_bot_risk():
    src=inspect.getsource(ResearchExperimentService);assert 'PositionModel' not in src and 'BotRuntime' not in src and 'approve_risk' not in src and 'decrypt' not in src

def test_experiment_version(): assert EXPERIMENT_VERSION=='1.0.0'
