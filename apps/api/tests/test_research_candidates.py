import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from models import Base, CandidatePromotionEvaluation, ResearchCandidateStrategy, ResearchExperiment, ResearchHypothesis, ResearchObservation, TradeOutcome
from packages.research.candidates import (
    CANDIDATE_STATUSES, CANDIDATE_VERSION, GATE_VERSION, CandidateCreateRequest,
    PromotionEvaluateRequest, ResearchCandidateService, canonical_hash,
)

D=Decimal

@pytest.fixture
def cdb(tmp_path):
    e=create_engine(f"sqlite:///{tmp_path/'candidates.db'}")
    Base.metadata.create_all(e); S=sessionmaker(bind=e); db=S()
    try: yield db
    finally: db.close(); e.dispose()

def seed(cdb, *, passed=True, completed=True, hypothesis_regime=None, n=12, symbol='BTC/USDT'):
    now=datetime(2026,8,1,tzinfo=timezone.utc)
    h=ResearchHypothesis(hypothesis_type='parameter_candidate',title='RSI candidate',description='observed association; requires validation',status='testing',strategy_name='alpha',strategy_version='1.0',symbol=symbol,timeframe='1h',regime=hypothesis_regime,feature_conditions={'rsi_gte':'50'},entry_conditions={'rsi_gte':'50'},exit_conditions={},risk_conditions={},evidence_summary={'association':'candidate'},source_metrics={'baseline_expectancy':'2'},sample_size=n,confidence_score=D('.7'),priority_score=D('.8'),hypothesis_version='1.0.0',configuration={'rule':'rsi'},configuration_hash='b'*64)
    cdb.add(h); cdb.flush()
    outcomes=[]
    for i in range(n):
        regime='trending_bull' if i < max(1,int(n*.67)) else 'ranging'
        pnl=D('10') if i%3 else D('-4')
        o=TradeOutcome(source_position_id=uuid4(),exchange='demo',symbol=symbol,timeframe='1h',strategy_name='alpha',strategy_version='1.0',strategy_config_hash='a'*64,side='long',entry_time=now+timedelta(hours=i),exit_time=now+timedelta(hours=i,minutes=30),entry_price=D('100'),exit_price=D('101'),quantity=D('1'),notional=D('100'),gross_pnl=pnl+D('1.5'),net_pnl=pnl,fees=D('1'),slippage=D('.5'),holding_time_seconds=D('1800'),exit_reason='take_profit' if pnl>0 else 'stop_loss',mae=D('2'),mfe=D('5'),return_pct=pnl/100,risk_amount=D('10'),r_multiple=pnl/10,regime_at_entry=regime,outcome_version='1.0.0',context={'execution':'complete'})
        cdb.add(o); outcomes.append(o)
    cdb.flush()
    exp=ResearchExperiment(hypothesis_id=h.id,experiment_type='parameter_comparison',status='completed' if completed else 'running',symbol=symbol,timeframe='1h',strategy_name='alpha',strategy_version='1.0',train_start=now,train_end=now+timedelta(hours=7,minutes=30),validation_start=now+timedelta(hours=8),validation_end=now+timedelta(hours=n-1,minutes=30),configuration={'scope_start':now.isoformat(),'scope_end':(now+timedelta(hours=n)).isoformat(),'evidence_outcome_ids':[str(x.id) for x in outcomes]},configuration_hash='c'*64,experiment_version='1.0.0',hypothesis_version='1.0.0',hypothesis_configuration_hash=h.configuration_hash,sample_size=n,baseline_sample_size=n,result_metrics={'trade_count':n,'expectancy':'4','profit_factor':'2.5','max_drawdown':'8','gross_pnl':'100','net_pnl':'80','fees':'12','slippage':'6','train':{'trade_count':8,'expectancy':'4'},'validation':{'trade_count':4,'expectancy':'3'}},baseline_metrics={'trade_count':n,'expectancy':'2','profit_factor':'1.5','net_pnl':'40'},comparison_metrics={'candidate_parameters':{'entry_conditions':{'rsi_gte':'50'}},'baseline_parameters':{'rsi_gte':'baseline_unfiltered'}},score=D('.75'),stability_score=D('.8'),data_quality_score=D('.9'),passed=passed,failure_reasons=[] if passed else [{'code':'minimum_sample_size'}],started_at=now,completed_at=now+timedelta(days=1) if completed else None)
    cdb.add(exp); cdb.commit(); return h,exp,outcomes

def create(cdb, **seed_kwargs):
    h,e,rows=seed(cdb,**seed_kwargs); c=ResearchCandidateService(cdb).create(CandidateCreateRequest(source_experiment_id=e.id)); return h,e,rows,c

def passing_eval(cdb,cid,**kwargs):
    defaults={'minimum_historical_sample':5,'minimum_expectancy':D('0'),'minimum_profit_factor':D('1'),'maximum_drawdown':D('100'),'minimum_stability':D('.3'),'minimum_data_quality':D('.4'),'maximum_execution_cost_ratio':D('.5'),'maximum_regime_concentration':D('.9')}
    defaults.update(kwargs); return ResearchCandidateService(cdb).evaluate(cid,PromotionEvaluateRequest(**defaults))

def test_candidate_from_passing_experiment(cdb):
    h,e,_,c=create(cdb); assert c.source_hypothesis_id==h.id and c.source_experiment_id==e.id and c.status=='draft'

def test_failed_experiment_cannot_create_candidate(cdb):
    _,e,_=seed(cdb,passed=False)
    with pytest.raises(ValueError): ResearchCandidateService(cdb).create(CandidateCreateRequest(source_experiment_id=e.id))

def test_incomplete_experiment_cannot_create_candidate(cdb):
    _,e,_=seed(cdb,completed=False)
    with pytest.raises(ValueError): ResearchCandidateService(cdb).create(CandidateCreateRequest(source_experiment_id=e.id))

def test_deterministic_candidate_configuration_hash(cdb):
    _,_,_,c=create(cdb); assert c.configuration_hash==canonical_hash(c.configuration) and canonical_hash({'a':1,'b':2})==canonical_hash({'b':2,'a':1})

def test_candidate_idempotency(cdb):
    _,e,_=seed(cdb);svc=ResearchCandidateService(cdb);a=svc.create(CandidateCreateRequest(source_experiment_id=e.id));b=svc.create(CandidateCreateRequest(source_experiment_id=e.id,name='ignored on duplicate'));assert a.id==b.id and cdb.scalar(select(func.count()).select_from(ResearchCandidateStrategy))==1

def test_provenance_preservation(cdb):
    h,e,_,c=create(cdb); assert c.configuration['source_hypothesis']['configuration_hash']==h.configuration_hash and c.configuration['source_experiment']['configuration_hash']==e.configuration_hash and c.evidence_summary['historical_scope']['evidence_outcome_ids']

def test_sample_size_promotion_gate(cdb):
    *_,c=create(cdb,n=6); p=passing_eval(cdb,c.id,minimum_historical_sample=20); assert not p.sample_gate_passed and not p.overall_passed

def test_expectancy_gate(cdb):
    *_,c=create(cdb); p=passing_eval(cdb,c.id,minimum_expectancy=D('10')); assert not p.expectancy_gate_passed

def test_profit_factor_gate(cdb):
    *_,c=create(cdb); p=passing_eval(cdb,c.id,minimum_profit_factor=D('3')); assert not p.profit_factor_gate_passed

def test_drawdown_gate(cdb):
    *_,c=create(cdb); p=passing_eval(cdb,c.id,maximum_drawdown=D('2')); assert not p.drawdown_gate_passed

def test_stability_gate(cdb):
    *_,c=create(cdb); p=passing_eval(cdb,c.id,minimum_stability=D('.9')); assert not p.stability_gate_passed

def test_data_quality_gate(cdb):
    *_,c=create(cdb); p=passing_eval(cdb,c.id,minimum_data_quality=D('.95')); assert not p.data_quality_gate_passed

def test_execution_cost_gate(cdb):
    *_,c=create(cdb); p=passing_eval(cdb,c.id,maximum_execution_cost_ratio=D('.1')); assert not p.execution_cost_gate_passed

def test_regime_robustness_gate(cdb):
    *_,c=create(cdb,hypothesis_regime='trending_bull'); p=passing_eval(cdb,c.id,maximum_regime_concentration=D('.5')); assert not p.regime_robustness_gate_passed

def test_anti_overfitting_warnings(cdb):
    *_,c=create(cdb,n=6); p=passing_eval(cdb,c.id,minimum_historical_sample=5); codes={x['code'] for x in p.warnings}; assert 'tiny_sample' in codes and 'overfitting_not_proven_absent' in codes

def test_train_validation_inconsistency(cdb):
    _,e,_,c=create(cdb); e.result_metrics={**e.result_metrics,'train':{'trade_count':8,'expectancy':'4'},'validation':{'trade_count':4,'expectancy':'-1'}};cdb.commit(); p=passing_eval(cdb,c.id);assert 'train_validation_inconsistency' in {x['code'] for x in p.warnings}

def test_one_symbol_dependence(cdb):
    *_,c=create(cdb); p=passing_eval(cdb,c.id); assert 'one_symbol_dependence' in {x['code'] for x in p.warnings}

def test_one_regime_dependence(cdb):
    *_,c=create(cdb,hypothesis_regime='trending_bull'); p=passing_eval(cdb,c.id,maximum_regime_concentration=D('.9')); assert 'one_regime_dependence' in {x['code'] for x in p.warnings}

def test_failed_gates_block_approval(cdb):
    *_,c=create(cdb); p=passing_eval(cdb,c.id,minimum_profit_factor=D('99')); assert not p.overall_passed and ResearchCandidateService(cdb).get(c.id).status=='blocked'
    with pytest.raises(ValueError): ResearchCandidateService(cdb).approve_demo(c.id)

def test_passed_gates_allow_review_request(cdb):
    *_,c=create(cdb); p=passing_eval(cdb,c.id); assert p.overall_passed; r=ResearchCandidateService(cdb).request_review(c.id); assert r.status=='review_required'

def test_review_required_before_demo_approval(cdb):
    *_,c=create(cdb); passing_eval(cdb,c.id)
    with pytest.raises(ValueError): ResearchCandidateService(cdb).approve_demo(c.id)

def test_explicit_demo_approval(cdb):
    *_,c=create(cdb); svc=ResearchCandidateService(cdb);passing_eval(cdb,c.id);svc.request_review(c.id);approved=svc.approve_demo(c.id);assert approved.status=='approved_for_demo'

def test_candidate_rejection(cdb):
    *_,c=create(cdb); assert ResearchCandidateService(cdb).reject(c.id).status=='rejected'

def test_approved_for_demo_does_not_start_bot(cdb):
    *_,c=create(cdb);svc=ResearchCandidateService(cdb);passing_eval(cdb,c.id);svc.request_review(c.id);svc.approve_demo(c.id);src=inspect.getsource(ResearchCandidateService);assert 'start_bot(' not in src and 'BotRuntimeStateModel' not in src

def test_approved_for_demo_does_not_submit_order(cdb):
    *_,c=create(cdb);src=inspect.getsource(ResearchCandidateService);assert 'place_order(' not in src and 'submit_order(' not in src and 'DemoOrderModel' not in src

def test_approved_for_demo_does_not_modify_strategy_config(cdb):
    h,_,_,c=create(cdb);before=(dict(h.configuration),h.configuration_hash);svc=ResearchCandidateService(cdb);passing_eval(cdb,c.id);svc.request_review(c.id);svc.approve_demo(c.id);cdb.refresh(h);assert (h.configuration,h.configuration_hash)==before

def test_no_live_approval_capability():
    assert 'approved_for_live' not in CANDIDATE_STATUSES and not hasattr(ResearchCandidateService,'approve_live')

def test_no_risk_bypass():
    src=inspect.getsource(__import__('packages.research.candidates',fromlist=['x'])); assert 'packages.risk' not in src and 'approve_risk' not in src

def test_no_credential_access():
    src=inspect.getsource(__import__('packages.research.candidates',fromlist=['x'])); assert 'decrypt_exchange' not in src and 'ccxt' not in src and 'exchange.adapter' not in src

def test_research_observation_lifecycle_events(cdb):
    *_,c=create(cdb);svc=ResearchCandidateService(cdb);passing_eval(cdb,c.id);svc.request_review(c.id);svc.approve_demo(c.id);events=cdb.execute(select(ResearchObservation.event_type).where(ResearchObservation.context.is_not(None))).scalars().all();assert {'candidate_created','candidate_evaluated','candidate_review_requested','candidate_approved_for_demo'}.issubset(set(events))

def test_candidate_rejected_observation(cdb):
    *_,c=create(cdb);ResearchCandidateService(cdb).reject(c.id);assert cdb.execute(select(ResearchObservation).where(ResearchObservation.event_type=='candidate_rejected')).scalar_one()

def test_candidate_filtering_retrieval(cdb):
    h,e,_,c=create(cdb);svc=ResearchCandidateService(cdb);assert svc.get(c.id).id==c.id and len(svc.list(status='draft',base_strategy='alpha',source_hypothesis=h.id,source_experiment=e.id,symbol='BTC/USDT',timeframe='1h',minimum_experiment_score=D('.7'),minimum_stability=D('.7')))==1

def test_promotion_result_retrieval(cdb):
    *_,c=create(cdb);p=passing_eval(cdb,c.id);assert ResearchCandidateService(cdb).promotion(c.id).id==p.id

def test_candidate_version(): assert CANDIDATE_VERSION=='1.0.0'
def test_gate_version(): assert GATE_VERSION=='1.0.0'
