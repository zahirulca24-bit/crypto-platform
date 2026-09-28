from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import inspect

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, ResearchObservation, ResearchHypothesis, ResearchExperiment, ResearchCandidateStrategy, CandidatePromotionEvaluation
from packages.research.integration import ResearchIntegrationService, EXPECTED_MIGRATION_HEAD
from routers.research import router

D = Decimal

@pytest.fixture
def idb(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'integration.db'}")
    Base.metadata.create_all(engine); Session=sessionmaker(bind=engine); db=Session()
    try: yield db
    finally: db.close(); engine.dispose()


def seed_chain(db):
    now=datetime(2026,9,8,tzinfo=timezone.utc)
    obs=ResearchObservation(event_type='hypothesis_proposed',source='research',exchange='demo',symbol='BTC/USDT',timeframe='1h',strategy_name='alpha',strategy_version='1.0',realized_pnl=D('5.25'),fees=D('.5'),slippage=D('.1'),context={'stage':'hypothesis'},observed_at=now)
    db.add(obs); db.flush()
    h=ResearchHypothesis(hypothesis_type='regime_performance',title='candidate',description='observed association; requires validation',status='testing',strategy_name='alpha',strategy_version='1.0',symbol='BTC/USDT',timeframe='1h',regime='trending_bull',feature_conditions={},entry_conditions={},exit_conditions={},risk_conditions={},evidence_summary={'outcome_ids':[]},source_metrics={'expectancy':'2'},sample_size=20,confidence_score=D('.7'),priority_score=D('.8'),hypothesis_version='1.0.0',configuration={'scope':'all'},configuration_hash='a'*64,observation_event_id=obs.event_id)
    db.add(h); db.flush()
    exp=ResearchExperiment(hypothesis_id=h.id,experiment_type='regime_validation',status='completed',symbol='BTC/USDT',timeframe='1h',strategy_name='alpha',strategy_version='1.0',train_start=now-timedelta(days=10),train_end=now-timedelta(days=6),validation_start=now-timedelta(days=5),validation_end=now-timedelta(days=1),configuration={'evidence_outcome_ids':[],'scope_start':(now-timedelta(days=10)).isoformat(),'scope_end':now.isoformat()},configuration_hash='b'*64,experiment_version='1.0.0',hypothesis_version='1.0.0',hypothesis_configuration_hash=h.configuration_hash,sample_size=20,baseline_sample_size=20,result_metrics={'expectancy':'2','profit_factor':'1.5','max_drawdown':'3'},baseline_metrics={'expectancy':'1'},comparison_metrics={},score=D('.75'),stability_score=D('.8'),data_quality_score=D('.9'),passed=True,failure_reasons=[],started_at=now-timedelta(hours=2),completed_at=now-timedelta(hours=1))
    db.add(exp); db.flush()
    c=ResearchCandidateStrategy(name='candidate',description='research only',source_hypothesis_id=h.id,source_experiment_id=exp.id,base_strategy_name='alpha',base_strategy_version='1.0',candidate_version='1.0.0',symbol_scope={'symbols':['BTC/USDT']},timeframe_scope={'timeframes':['1h']},regime_scope={'regimes':['trending_bull']},feature_conditions={},entry_conditions={},exit_conditions={},risk_conditions={},parameter_overrides={},evidence_summary={'historical_scope':{'evidence_outcome_ids':[]}},evaluation_metrics={'result':exp.result_metrics},experiment_score=exp.score,stability_score=exp.stability_score,data_quality_score=exp.data_quality_score,status='eligible',configuration={'historical_scope':{'evidence_outcome_ids':[]}},configuration_hash='c'*64,research_observation_id=obs.event_id)
    db.add(c); db.flush()
    p=CandidatePromotionEvaluation(candidate_id=c.id,gate_version='1.0.0',overall_passed=True,review_required=True,sample_gate_passed=True,expectancy_gate_passed=True,profit_factor_gate_passed=True,drawdown_gate_passed=True,stability_gate_passed=True,data_quality_gate_passed=True,execution_cost_gate_passed=True,regime_robustness_gate_passed=True,gate_results={'all':True},failure_reasons=[],warnings=[],configuration={'minimum_sample':5},configuration_hash='d'*64,evaluated_at=now)
    db.add(p); db.commit(); return obs,h,exp,c,p


def test_research_router_registration():
    paths={r.path for r in router.routes}
    required={'/v1/research/overview','/v1/research/pipeline/status','/v1/research/learning-journal','/v1/research/lineage/{entity_type}/{entity_id}','/v1/research/health'}
    assert required.issubset(paths)


def test_overview_empty_state(idb):
    data=ResearchIntegrationService(idb).overview()
    assert all(v==0 for v in data['counts'].values())
    assert data['performance']['trade_count']==0 and data['recent_activity']==[]
    jsonable_encoder(data)


def test_overview_populated_state_and_serialization(idb):
    seed_chain(idb); data=ResearchIntegrationService(idb).overview()
    assert data['counts']['observations']==1 and data['counts']['hypotheses']==1
    assert data['counts']['experiments']==1 and data['counts']['candidates']==1
    assert data['experiments']['passed_count']==1 and data['candidate_status_counts']['eligible']==1
    encoded=jsonable_encoder(data); assert isinstance(encoded['experiments']['average_score'], (float,str,int))


def test_pipeline_status_is_research_readiness_only(idb):
    seed_chain(idb); data=ResearchIntegrationService(idb).pipeline_status()
    assert data['stages']['observation_ready'] and data['stages']['candidate_ready']
    assert data['counts']['promotion_evaluations']==1
    assert data['research_only'] is True and data['trading_activation'] is False


def test_learning_journal_newest_first_and_filters(idb):
    now=datetime(2026,9,8,tzinfo=timezone.utc)
    idb.add_all([
        ResearchObservation(event_type='market_regime',source='research',symbol='BTC/USDT',strategy_name='alpha',observed_at=now),
        ResearchObservation(event_type='candidate_created',source='research',symbol='ETH/USDT',strategy_name='beta',observed_at=now+timedelta(seconds=1)),
    ]); idb.commit(); svc=ResearchIntegrationService(idb)
    rows=svc.learning_journal(); assert [r['event_type'] for r in rows]==['candidate_created','market_regime']
    assert len(svc.learning_journal(event_type='market_regime',symbol='btc/usdt',strategy='alpha'))==1


def test_candidate_lineage_preserves_provenance(idb):
    _,h,e,c,p=seed_chain(idb); data=ResearchIntegrationService(idb).lineage('candidate',c.id)
    assert data['upstream']['hypothesis_id']==h.id and data['upstream']['experiment_id']==e.id
    assert data['downstream']['promotion_evaluations']==[p.id]
    assert data['research_governance_only'] and data['trading_activation'] is False
    jsonable_encoder(data)


def test_lineage_invalid_and_missing(idb):
    svc=ResearchIntegrationService(idb)
    with pytest.raises(ValueError): svc.lineage('bot',uuid4())
    with pytest.raises(LookupError): svc.lineage('candidate',uuid4())


def test_research_health_versions_and_migration_head(idb):
    data=ResearchIntegrationService(idb).health()
    assert data['status']=='ok' and data['postgresql_authoritative'] is True
    assert data['expected_migration_head']=='021_phase2_schema_compatibility'==EXPECTED_MIGRATION_HEAD
    assert set(data['versions'])=={'feature','regime','outcome','hypothesis','experiment','candidate','promotion_gate','ai_proposal','ai_prompt','ai_orchestrator','ai_review','ai_blueprint','ai_strategy_discovery_prompt','ai_blueprint_validation','ai_strategy_evolution','ai_champion_challenger','ai_strategy_regime_profile','ai_research_portfolio','ai_shadow_session','ai_candidate_handoff','ai_monitor_policy','ai_monitor_trigger','ai_adaptive_research_job','ai_demo_manifest','ai_runtime_compatibility','ai_demo_runtime_release'}
    assert data['external_exchange_check_performed'] is False and data['external_ai_required'] is False


def test_no_live_approval_route_or_state():
    paths={r.path for r in router.routes}; assert not any('approve-live' in p for p in paths)
    source=inspect.getsource(__import__('packages.research.candidates',fromlist=['x']))
    assert 'approved_for_live' not in source


def test_integration_module_has_no_execution_or_credentials_dependency():
    source=inspect.getsource(__import__('packages.research.integration',fromlist=['x']))
    forbidden=['ccxt','decrypt_credentials','decrypt_exchange','place_order(','submit_order(','start_bot(','approve_risk(','packages.exchange','packages.risk','packages.runtime']
    assert all(token not in source for token in forbidden)


def test_candidate_approval_semantics_remain_research_only(idb):
    _,_,_,c,_=seed_chain(idb); data=ResearchIntegrationService(idb).lineage('candidate',c.id)
    assert data['trading_activation'] is False


def test_phase3_values_json_serializable(idb):
    obs,_,_,c,_=seed_chain(idb)
    payload={'uuid':c.id,'decimal':D('1.234567'),'datetime':obs.observed_at}
    encoded=jsonable_encoder(payload)
    assert encoded['uuid']==str(c.id) and encoded['decimal']==1.234567 and isinstance(encoded['datetime'],str)


def test_full_phase3_lineage_chain(idb):
    from models import OHLCVCandle, PositionModel, MarketFeatureSnapshot, MarketRegimeSnapshot, TradeOutcome
    now=datetime(2026,9,1,tzinfo=timezone.utc)
    obs=ResearchObservation(event_type='market_regime',source='research',exchange='demo',symbol='BTC/USDT',timeframe='1h',observed_at=now)
    idb.add(obs); idb.flush()
    candle=OHLCVCandle(exchange='demo',symbol='BTC/USDT',timeframe='1h',open_time=now,open=D('100'),high=D('105'),low=D('95'),close=D('102'),volume=D('1000'),is_closed=True)
    idb.add(candle); idb.flush()
    feature=MarketFeatureSnapshot(candle_id=candle.id,observation_event_id=obs.event_id,exchange='demo',symbol='BTC/USDT',timeframe='1h',candle_open_time=now,feature_version='1.0.0',configuration={},configuration_hash='1'*64,rsi=D('55'))
    idb.add(feature); idb.flush()
    regime=MarketRegimeSnapshot(feature_snapshot_id=feature.id,observation_event_id=obs.event_id,exchange='demo',symbol='BTC/USDT',timeframe='1h',candle_open_time=now,regime='trending_bull',confidence_score=D('.8'),regime_version='1.0.0',configuration={},configuration_hash='2'*64,supporting_signals={'trend':True},reason='deterministic trend signals',current_regime='trending_bull',changed=False)
    idb.add(regime); idb.flush()
    position=PositionModel(id=uuid4(),symbol='BTC/USDT',status='closed',position_json={'status':'closed'},opened_at=now,updated_at=now+timedelta(hours=1))
    idb.add(position); idb.flush()
    outcome=TradeOutcome(source_position_id=position.id,observation_event_id=obs.event_id,exchange='demo',symbol='BTC/USDT',timeframe='1h',strategy_name='alpha',strategy_version='1.0',strategy_config_hash='3'*64,side='long',entry_time=now,exit_time=now+timedelta(hours=1),entry_price=D('100'),exit_price=D('102'),quantity=D('1'),notional=D('100'),gross_pnl=D('2'),net_pnl=D('1.5'),fees=D('.4'),slippage=D('.1'),holding_time_seconds=D('3600'),exit_reason='strategy_exit',mae=D('1'),mfe=D('3'),return_pct=D('2'),risk_amount=D('1'),r_multiple=D('1.5'),regime_at_entry='trending_bull',regime_at_exit='trending_bull',entry_feature_snapshot_id=feature.id,exit_feature_snapshot_id=feature.id,entry_regime_snapshot_id=regime.id,exit_regime_snapshot_id=regime.id,outcome_version='1.0.0',context={})
    idb.add(outcome); idb.flush()
    h=ResearchHypothesis(hypothesis_type='regime_performance',title='trend association',description='observed association; requires validation',status='testing',strategy_name='alpha',strategy_version='1.0',symbol='BTC/USDT',timeframe='1h',regime='trending_bull',feature_conditions={},entry_conditions={},exit_conditions={},risk_conditions={},evidence_summary={'outcome_ids':[str(outcome.id)]},source_metrics={},sample_size=1,confidence_score=D('.2'),priority_score=D('.2'),hypothesis_version='1.0.0',configuration={'evidence_outcome_ids':[str(outcome.id)]},configuration_hash='4'*64,observation_event_id=obs.event_id)
    idb.add(h); idb.flush()
    exp=ResearchExperiment(hypothesis_id=h.id,experiment_type='regime_validation',status='completed',symbol='BTC/USDT',timeframe='1h',strategy_name='alpha',strategy_version='1.0',train_start=now,train_end=now+timedelta(minutes=30),validation_start=now+timedelta(minutes=31),validation_end=now+timedelta(hours=1),configuration={'evidence_outcome_ids':[str(outcome.id)]},configuration_hash='5'*64,experiment_version='1.0.0',hypothesis_version='1.0.0',hypothesis_configuration_hash=h.configuration_hash,sample_size=1,baseline_sample_size=1,result_metrics={'expectancy':'1.5'},baseline_metrics={'expectancy':'0'},comparison_metrics={},score=D('.4'),stability_score=D('.4'),data_quality_score=D('.5'),passed=True,failure_reasons=[],started_at=now,completed_at=now+timedelta(hours=2),start_observation_event_id=obs.event_id,completion_observation_event_id=obs.event_id)
    idb.add(exp); idb.flush()
    c=ResearchCandidateStrategy(name='trend candidate',description='research only',source_hypothesis_id=h.id,source_experiment_id=exp.id,base_strategy_name='alpha',base_strategy_version='1.0',candidate_version='1.0.0',symbol_scope={'symbols':['BTC/USDT']},timeframe_scope={'timeframes':['1h']},regime_scope={'regimes':['trending_bull']},feature_conditions={},entry_conditions={},exit_conditions={},risk_conditions={},parameter_overrides={},evidence_summary={'historical_scope':{'evidence_outcome_ids':[str(outcome.id)]}},evaluation_metrics={},experiment_score=exp.score,stability_score=exp.stability_score,data_quality_score=exp.data_quality_score,status='eligible',configuration={'historical_scope':{'evidence_outcome_ids':[str(outcome.id)]}},configuration_hash='6'*64,research_observation_id=obs.event_id)
    idb.add(c); idb.flush()
    promotion=CandidatePromotionEvaluation(candidate_id=c.id,gate_version='1.0.0',overall_passed=True,review_required=True,sample_gate_passed=True,expectancy_gate_passed=True,profit_factor_gate_passed=True,drawdown_gate_passed=True,stability_gate_passed=True,data_quality_gate_passed=True,execution_cost_gate_passed=True,regime_robustness_gate_passed=True,gate_results={},failure_reasons=[],warnings=[],configuration={},configuration_hash='7'*64,evaluated_at=now)
    idb.add(promotion); idb.commit()
    svc=ResearchIntegrationService(idb)
    candidate_lineage=svc.lineage('candidate',c.id); experiment_lineage=svc.lineage('experiment',exp.id); outcome_lineage=svc.lineage('outcome',outcome.id)
    assert candidate_lineage['upstream']['experiment_id']==exp.id
    assert str(outcome.id) in experiment_lineage['upstream']['evidence_outcome_ids']
    assert exp.id in outcome_lineage['downstream']['experiments'] and h.id in outcome_lineage['downstream']['hypotheses']
    assert svc.lineage('regime',regime.id)['upstream']['feature_snapshot_id']==feature.id
    assert svc.lineage('feature',feature.id)['upstream']['candle_id']==candle.id


def test_main_registers_research_router_without_importing_exchange_stack():
    from pathlib import Path
    main_source=(Path(__file__).resolve().parents[1]/'main.py').read_text()
    assert 'from routers.research import router as research_router' in main_source
    assert 'app.include_router(research_router)' in main_source


def test_best_effort_observation_failure_is_isolated_and_logged(monkeypatch, caplog):
    from packages.research import service as research_service
    from packages.research.models import ObservationCreate
    class FakeDB:
        rolled_back=False
        def rollback(self): self.rolled_back=True
    def fail_record(self, observation):
        raise RuntimeError('simulated research persistence failure')
    monkeypatch.setattr(research_service.ResearchObservationService, 'record', fail_record)
    db=FakeDB()
    with caplog.at_level('ERROR'):
        research_service.observe_best_effort(db, ObservationCreate(event_type='test.event', source='test'))
    assert db.rolled_back is True
    assert 'R&D observation persistence failed' in caplog.text
