import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from models import AIResearchProposal, AIProposalReview, AIResearchRun, AIStrategyBlueprint, ResearchExperiment, ResearchHypothesis, ResearchObservation
from packages.research.ai.discovery import StrategyDiscoveryService, canonical_hash
from packages.research.ai.schemas import BLUEPRINT_VERSION, STRATEGY_DISCOVERY_PROMPT_VERSION, BlueprintGenerateRequest, StructuredStrategyBlueprint

class FakeBlueprintProvider:
    provider_name='fake_research'; model_name='fake-model'; configured=True
    def __init__(self,payload=None): self.calls=0; self.payload=payload or blueprint_payload()
    def generate_strategy_blueprint(self,**kwargs): self.calls+=1; return self.payload, {'fake':True}
    def generate_research_proposals(self,**kwargs): raise AssertionError('wrong provider method')
    def analyze_research_context(self,**kwargs): return {}
    def health_check(self): return {'configured':True,'provider':self.provider_name,'model':self.model_name}

def blueprint_payload(**kw):
    d={'name':'Bull RSI EMA research blueprint','description':'Non-causal candidate for deterministic historical validation','blueprint_type':'multi_signal','base_strategy_name':'momentum','base_strategy_version':'1.0','symbol_scope':['BTC/USDT'],'timeframe_scope':['1h'],'regime_scope':['trending_bull'],'feature_requirements':['rsi','ema'],'indicator_requirements':['rsi','ema','atr'],'entry_logic':{'all':[{'indicator':'rsi','operator':'<','value':40},{'indicator':'ema','operator':'>','reference':'sma'}],'any':[]},'exit_logic':{'take_profit_pct':2.0,'stop_loss_pct':1.0},'protection_logic':{'stop_loss_required':True},'risk_constraints':{'max_risk_per_trade_pct':1.0,'maximum_spread':0.5},'parameter_space':{'rsi_threshold':{'min':30,'max':40,'step':5},'atr_multiplier':{'values':[1,1.5,2]}},'expected_behavior':{'association_only':True},'invalidation_conditions':{'negative_expectancy':True},'estimated_data_requirements':{'minimum_trades':20}}
    d.update(kw); return d

def seed_hypothesis(db,sample=20):
    h=ResearchHypothesis(hypothesis_type='feature_condition',title='RSI EMA association',description='Observed association requiring validation',status='testing',strategy_name='momentum',strategy_version='1.0',symbol='BTC/USDT',timeframe='1h',regime='trending_bull',feature_conditions={'rsi':{'lt':40}},entry_conditions={'ema_fast':{'gt':'ema_slow'}},exit_conditions={'tp':2},risk_conditions={'max_risk_pct':1},evidence_summary={'requires_validation':True},source_metrics={'baseline':{}},sample_size=sample,confidence_score=Decimal('0.7'),priority_score=Decimal('0.8'),hypothesis_version='1.0.0',configuration={},configuration_hash='a'*64)
    db.add(h); db.commit(); db.refresh(h); return h

def seed_experiment(db,h,passed=True):
    now=datetime.now(timezone.utc); e=ResearchExperiment(hypothesis_id=h.id,experiment_type='hypothesis_validation',status='completed',symbol='BTC/USDT',timeframe='1h',strategy_name='momentum',strategy_version='1.0',train_start=now-timedelta(days=30),train_end=now-timedelta(days=10),validation_start=now-timedelta(days=9),validation_end=now,configuration={},configuration_hash='b'*64,experiment_version='1.0.0',hypothesis_version=h.hypothesis_version,hypothesis_configuration_hash=h.configuration_hash,sample_size=30,baseline_sample_size=30,result_metrics={'expectancy':1.2,'profit_factor':1.6},baseline_metrics={'expectancy':0.4,'profit_factor':1.1},comparison_metrics={'expectancy_difference':0.8},score=Decimal('0.8'),stability_score=Decimal('0.75'),data_quality_score=Decimal('0.9'),passed=passed,failure_reasons=[],started_at=now-timedelta(minutes=1),completed_at=now)
    db.add(e); db.commit(); db.refresh(e); return e

def seed_reviewed_proposal(db):
    p=AIResearchProposal(provider='fake',model_name='fake-model',prompt_version='1.0.0',proposal_type='feature_combination_candidate',title='Reviewed feature idea',summary='Observed association',strategy_name='momentum',symbol='BTC/USDT',timeframe='1h',regime='trending_bull',hypothesis_statement='RSI plus EMA may improve expectancy',rationale='Persisted evidence only',feature_conditions={'rsi':{'lt':40}},entry_conditions={},exit_conditions={},risk_conditions={},parameter_suggestions={},supporting_evidence={},referenced_observation_ids=[],referenced_outcome_ids=[],referenced_hypothesis_ids=[],referenced_experiment_ids=[],data_scope={'context_ids':{}},model_confidence=Decimal('0.9'),research_priority=Decimal('0.8'),raw_model_metadata={},status='review_required',proposal_version='1.0.0',configuration={},configuration_hash='c'*64)
    db.add(p); db.commit(); db.refresh(p)
    rrun=AIResearchRun(run_type='broad_scan',status='completed',provider='fake',model_name='fake-model',prompt_version='1.0.0',orchestrator_version='1.0.0',symbol_scope=['BTC/USDT'],timeframe_scope=['1h'],regime_scope=['trending_bull'],strategy_scope=['momentum'],data_start=None,data_end=None,context_summary={},evidence_scope={},proposals_requested=1,proposals_generated=1,proposals_accepted=1,proposals_suppressed=0,proposals_rejected=0,run_metrics={},warnings=[],failure_reason=None,configuration={},configuration_hash='d'*64,started_at=datetime.now(timezone.utc),completed_at=datetime.now(timezone.utc))
    db.add(rrun);db.commit();db.refresh(rrun)
    rev=AIProposalReview(proposal_id=p.id,research_run_id=rrun.id,review_version='1.0.0',evidence_score=Decimal('.8'),novelty_score=Decimal('.8'),testability_score=Decimal('.8'),data_quality_score=Decimal('.8'),safety_score=Decimal('1'),overall_score=Decimal('.82'),accepted_for_review=True,suppressed=False,rejection_reasons=[],warnings=[],review_metrics={},configuration={},configuration_hash='e'*64)
    db.add(rev);db.commit();db.refresh(rev);return p,rev

def test_generate_from_reviewed_proposal(db_session):
    p,_=seed_reviewed_proposal(db_session); fp=FakeBlueprintProvider(); row=StrategyDiscoveryService(db_session,fp).generate(BlueprintGenerateRequest(source_ai_proposal_id=p.id)); assert row.source_ai_proposal_id==p.id and row.status=='draft' and fp.calls==1

def test_generate_from_hypothesis(db_session):
    h=seed_hypothesis(db_session); row=StrategyDiscoveryService(db_session,FakeBlueprintProvider()).generate(BlueprintGenerateRequest(source_hypothesis_id=h.id)); assert row.source_hypothesis_id==h.id and row.readiness_score>0

def test_generate_from_completed_experiment(db_session):
    h=seed_hypothesis(db_session); e=seed_experiment(db_session,h); row=StrategyDiscoveryService(db_session,FakeBlueprintProvider()).generate(BlueprintGenerateRequest(source_experiment_id=e.id)); assert row.source_experiment_id==e.id and row.source_hypothesis_id==h.id

def test_unreviewed_proposal_rejected(db_session):
    p,_=seed_reviewed_proposal(db_session); p.status='generated'; db_session.commit()
    with pytest.raises(ValueError): StrategyDiscoveryService(db_session,FakeBlueprintProvider()).generate(BlueprintGenerateRequest(source_ai_proposal_id=p.id))

def test_structured_logic_allowlist_operator_and_unsupported_indicator():
    StructuredStrategyBlueprint.model_validate(blueprint_payload())
    bad=blueprint_payload(indicator_requirements=['magic_indicator'])
    with pytest.raises(ValueError): StructuredStrategyBlueprint.model_validate(bad)
    bad=blueprint_payload(entry_logic={'all':[{'indicator':'rsi','operator':'~~','value':40}],'any':[]})
    with pytest.raises(ValueError): StructuredStrategyBlueprint.model_validate(bad)

def test_no_future_data_and_no_executable_code_blocked(db_session):
    h=seed_hypothesis(db_session); svc=StrategyDiscoveryService(db_session,FakeBlueprintProvider(blueprint_payload(expected_behavior={'note':'use next candle future close'}))); row=svc.generate(BlueprintGenerateRequest(source_hypothesis_id=h.id)); assert 'future_data_condition_not_allowed' in row.blocking_reasons
    db_session.query(AIStrategyBlueprint).delete();db_session.commit()
    svc=StrategyDiscoveryService(db_session,FakeBlueprintProvider(blueprint_payload(expected_behavior={'script':'eval(x)'}))); row=svc.generate(BlueprintGenerateRequest(source_hypothesis_id=h.id)); assert 'executable_code_not_allowed' in row.blocking_reasons

def test_risk_protection_validation(db_session):
    h=seed_hypothesis(db_session); row=StrategyDiscoveryService(db_session,FakeBlueprintProvider(blueprint_payload(protection_logic={'stop_loss_required':False}))).generate(BlueprintGenerateRequest(source_hypothesis_id=h.id)); assert 'mandatory_protection_cannot_be_disabled' in row.blocking_reasons

def test_parameter_range_validation():
    with pytest.raises(ValueError): StructuredStrategyBlueprint.model_validate(blueprint_payload(parameter_space={'x':{'min':10,'max':1,'step':1}}))
    with pytest.raises(ValueError): StructuredStrategyBlueprint.model_validate(blueprint_payload(parameter_space={'x':{'min':1,'max':10,'step':0}}))

def test_parameter_bounds_and_search_space_protection(monkeypatch,db_session):
    monkeypatch.setenv('AI_BLUEPRINT_MAX_PARAMETER_COMBINATIONS','10'); h=seed_hypothesis(db_session); payload=blueprint_payload(parameter_space={'a':{'values':[1,2,3,4]},'b':{'values':[1,2,3,4]}}); row=StrategyDiscoveryService(db_session,FakeBlueprintProvider(payload)).generate(BlueprintGenerateRequest(source_hypothesis_id=h.id)); assert row.estimated_data_requirements['parameter_combinations']==16 and 'parameter_search_space_exceeds_limit' in row.blocking_reasons

def test_complexity_and_excessive_block(monkeypatch,db_session):
    monkeypatch.setenv('AI_BLUEPRINT_MAX_CONDITIONS','100'); monkeypatch.setenv('AI_BLUEPRINT_MAX_PARAMETER_COMBINATIONS','100000'); h=seed_hypothesis(db_session); rules=[{'indicator':'rsi','operator':'<','value':i} for i in range(25)]; payload=blueprint_payload(entry_logic={'all':rules,'any':[]},parameter_space={f'p{i}':{'values':[1,2,3]} for i in range(8)}); row=StrategyDiscoveryService(db_session,FakeBlueprintProvider(payload)).generate(BlueprintGenerateRequest(source_hypothesis_id=h.id)); assert row.estimated_complexity in {'high','excessive'}

def test_readiness_deterministic_and_insufficient_evidence(db_session):
    h=seed_hypothesis(db_session,sample=1); svc=StrategyDiscoveryService(db_session,FakeBlueprintProvider()); a=svc.generate(BlueprintGenerateRequest(source_hypothesis_id=h.id)); assert 0<=a.readiness_score<=1; assert svc.readiness(a.id)['readiness_score']==a.readiness_score

def test_configuration_hash_and_deduplication(db_session):
    h=seed_hypothesis(db_session); svc=StrategyDiscoveryService(db_session,FakeBlueprintProvider()); a=svc.generate(BlueprintGenerateRequest(source_hypothesis_id=h.id)); b=svc.generate(BlueprintGenerateRequest(source_hypothesis_id=h.id)); assert a.id==b.id and len(a.configuration_hash)==64 and db_session.query(AIStrategyBlueprint).count()==1; assert canonical_hash({'b':1,'a':2})==canonical_hash({'a':2,'b':1})

def test_request_review_accept_validation_and_observations(monkeypatch,db_session):
    monkeypatch.setenv('AI_BLUEPRINT_MIN_READINESS_SCORE','0.3'); h=seed_hypothesis(db_session); e=seed_experiment(db_session,h); svc=StrategyDiscoveryService(db_session,FakeBlueprintProvider()); a=svc.generate(BlueprintGenerateRequest(source_experiment_id=e.id)); r=svc.request_review(a.id); assert r.status=='review_required'; accepted=svc.accept_for_validation(a.id); assert accepted.status=='accepted_for_validation'; events={x.event_type for x in db_session.query(ResearchObservation).all()}; assert {'ai_strategy_blueprint_generated','ai_strategy_blueprint_review_requested','ai_strategy_blueprint_accepted_for_validation'}<=events

def test_blocked_cannot_accept(db_session):
    h=seed_hypothesis(db_session); svc=StrategyDiscoveryService(db_session,FakeBlueprintProvider(blueprint_payload(protection_logic={'stop_loss_required':False}))); a=svc.generate(BlueprintGenerateRequest(source_hypothesis_id=h.id)); assert a.status=='rejected'
    with pytest.raises(ValueError): svc.accept_for_validation(a.id)

def test_reject_blueprint(db_session):
    h=seed_hypothesis(db_session); svc=StrategyDiscoveryService(db_session,FakeBlueprintProvider()); a=svc.generate(BlueprintGenerateRequest(source_hypothesis_id=h.id)); r=svc.reject(a.id); assert r.status=='rejected'; assert db_session.query(ResearchObservation).filter_by(event_type='ai_strategy_blueprint_rejected').count()==1

def test_filtering_retrieval_versions(db_session):
    h=seed_hypothesis(db_session); svc=StrategyDiscoveryService(db_session,FakeBlueprintProvider()); a=svc.generate(BlueprintGenerateRequest(source_hypothesis_id=h.id)); assert svc.get(a.id).id==a.id; rows=svc.list(blueprint_type='multi_signal',base_strategy='momentum',symbol='btc/usdt',timeframe='1h',regime='trending_bull',complexity=a.estimated_complexity); assert [x.id for x in rows]==[a.id]; assert a.blueprint_version==BLUEPRINT_VERSION=='1.0.0' and a.prompt_version==STRATEGY_DISCOVERY_PROMPT_VERSION=='1.0.0'

def test_acceptance_has_no_execution_side_effects(monkeypatch,db_session):
    monkeypatch.setenv('AI_BLUEPRINT_MIN_READINESS_SCORE','0.3'); h=seed_hypothesis(db_session); e=seed_experiment(db_session,h); before_exp=db_session.query(ResearchExperiment).count(); svc=StrategyDiscoveryService(db_session,FakeBlueprintProvider()); a=svc.generate(BlueprintGenerateRequest(source_experiment_id=e.id)); svc.request_review(a.id); svc.accept_for_validation(a.id); assert db_session.query(ResearchExperiment).count()==before_exp
    forbidden=('submit_order','place_order','start_bot','stop_bot','bypass_risk','approve_candidate','approve_live','create_candidate','create_experiment','modify_strategy_config','decrypt_credentials')
    assert all(not hasattr(svc,x) for x in forbidden)
    src=open('packages/research/ai/discovery.py').read().lower(); assert 'ccxt' not in src and 'eval(' not in src and 'exec(' not in src
