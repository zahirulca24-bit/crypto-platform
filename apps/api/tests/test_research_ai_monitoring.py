from __future__ import annotations
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from uuid import uuid4
import inspect
import pytest

from models import (
    ResearchMonitoringPolicy,ResearchTriggerEvent,AdaptiveResearchJob,ResearchMonitorWorkerStatus,
    ResearchObservation,PositionModel,TradeOutcome,OHLCVCandle,MarketFeatureSnapshot,MarketRegimeSnapshot,
    ShadowResearchSession,ResearchHypothesis,ResearchExperiment,ResearchCandidateStrategy,
)
from packages.research.ai.monitoring import ResearchMonitoringService,MonitoringPolicyCreate,MonitoringPolicyPatch,POLICY_VERSION,TRIGGER_VERSION,JOB_VERSION,TRIGGER_TYPES
from routers.research import router

NOW=datetime(2026,9,9,12,tzinfo=timezone.utc)

def policy(db,types,status='enabled',minimum=2,**kw):
    name=kw.pop('name','monitor')
    return ResearchMonitoringService(db).create_policy(MonitoringPolicyCreate(name=name,status=status,trigger_rules={'types':types},minimum_sample_size=minimum,cooldown_seconds=0,**kw))

def add_outcome(db,idx,pnl,fees=1,slip=.2):
    t=NOW+timedelta(hours=idx); pid=uuid4(); db.add(PositionModel(id=pid,symbol='BTC/USDT',status='closed',position_json={},opened_at=t,updated_at=t+timedelta(minutes=30)))
    r=TradeOutcome(source_position_id=pid,exchange='demo',symbol='BTC/USDT',timeframe='1h',strategy_name='alpha',strategy_version='1',strategy_config_hash='a'*64,side='long',entry_time=t,exit_time=t+timedelta(minutes=30),entry_price=D('100'),exit_price=D('101'),quantity=D('1'),notional=D('100'),gross_pnl=D(str(pnl+fees+slip)),net_pnl=D(str(pnl)),fees=D(str(fees)),slippage=D(str(slip)),holding_time_seconds=D('1800'),exit_reason='strategy_exit',mae=D('1'),mfe=D('2'),return_pct=D(str(pnl)),outcome_version='1.0.0',context={})
    db.add(r);db.flush();return r

def add_regime(db,idx,regime):
    t=NOW+timedelta(hours=idx); c=OHLCVCandle(exchange='demo',symbol='BTC/USDT',timeframe='1h',open_time=t,open=D('100'),high=D('101'),low=D('99'),close=D('100'),volume=D('100'),is_closed=True);db.add(c);db.flush()
    f=MarketFeatureSnapshot(candle_id=c.id,exchange='demo',symbol='BTC/USDT',timeframe='1h',candle_open_time=t,feature_version='1.0.0',configuration={},configuration_hash=(str(idx+1)*64)[:64]);db.add(f);db.flush()
    r=MarketRegimeSnapshot(feature_snapshot_id=f.id,exchange='demo',symbol='BTC/USDT',timeframe='1h',candle_open_time=t,regime=regime,confidence_score=D('.8'),regime_version='1.0.0',configuration={},configuration_hash=(str(idx+3)*64)[:64],supporting_signals={},reason='test',current_regime=regime,changed=idx>0,previous_regime=None);db.add(r);db.commit();return r

def test_policy_lifecycle_hash_filter_and_versions(db_session):
    svc=ResearchMonitoringService(db_session);p=policy(db_session,['regime_change'],symbol_scope=['btc/usdt'],timeframe_scope=['1h']); assert p.policy_version==POLICY_VERSION and len(p.configuration_hash)==64
    assert svc.policies(status='enabled',symbol='BTC/USDT')[0].id==p.id
    assert svc.pause(p.id).status=='paused' and svc.resume(p.id).status=='enabled'
    u=svc.update_policy(p.id,MonitoringPolicyPatch(description='updated')); assert u.description=='updated'

def test_regime_change_trigger_and_dedup(db_session):
    add_regime(db_session,0,'trending_bull');add_regime(db_session,1,'ranging');p=policy(db_session,['regime_change'],minimum=1,symbol_scope=['BTC/USDT'],timeframe_scope=['1h']);svc=ResearchMonitoringService(db_session)
    a=svc.evaluate(p.id,now=NOW+timedelta(hours=2));assert len(a)==1 and a[0].trigger_type=='regime_change' and a[0].status=='detected' and a[0].trigger_version==TRIGGER_VERSION
    assert svc.evaluate(p.id,now=NOW+timedelta(hours=3))==[] and db_session.query(ResearchTriggerEvent).count()==1

def test_performance_degradation_triggers_and_scores(db_session):
    for i,x in enumerate([10,10,-10,-10]):add_outcome(db_session,i,x,fees=1 if i<2 else 5,slip=.2 if i<2 else 2)
    types=['expectancy_degradation','drawdown_degradation','win_rate_degradation','profit_factor_degradation','execution_cost_drift']
    p=policy(db_session,types,minimum=2,symbol_scope=['BTC/USDT'],strategy_scope=['alpha']);rows=ResearchMonitoringService(db_session).evaluate(p.id,now=NOW+timedelta(hours=10));got={x.trigger_type for x in rows}
    assert {'expectancy_degradation','drawdown_degradation','win_rate_degradation','profit_factor_degradation','execution_cost_drift'}<=got
    assert all(D('0')<=x.severity_score<=D('1') and D('0')<=x.confidence_score<=D('1') for x in rows)

def test_insufficient_sample_suppresses_high_confidence(db_session):
    add_outcome(db_session,0,10);add_outcome(db_session,1,-10);p=policy(db_session,['expectancy_degradation'],minimum=5)
    assert ResearchMonitoringService(db_session).evaluate(p.id,now=NOW+timedelta(days=1))==[]

def test_shadow_drift_trigger(db_session):
    s=ShadowResearchSession(source_type='blueprint',session_version='1.0.0',status='completed',exchange='demo',symbol_scope=['BTC/USDT'],timeframe_scope=['1h'],regime_scope=[],configuration={'historical_data_quality':.8},configuration_hash='b'*64,execution_convention='signal_close_next_candle_open',fee_bps=D('10'),slippage_bps=D('5'),observed_candle_count=30,signal_count=10,simulated_trade_count=20,expected_metrics={'expectancy':1},observed_metrics={'expectancy':-.2},drift_metrics={'drift_score':.8,'signal_frequency_drift':.5},readiness_score=D('.2'),warnings=[],blocking_reasons=[]);db_session.add(s);db_session.commit()
    p=policy(db_session,['shadow_performance_drift'],minimum=10,shadow_session_id=s.id);rows=ResearchMonitoringService(db_session).evaluate(p.id,now=NOW);assert rows and rows[0].source_entity_type=='shadow_session'

def test_candidate_staleness_trigger(db_session):
    h=ResearchHypothesis(hypothesis_type='regime_performance',title='h',description='d',status='validated',feature_conditions={},entry_conditions={},exit_conditions={},risk_conditions={},evidence_summary={},source_metrics={},sample_size=20,confidence_score=D('.7'),priority_score=D('.7'),hypothesis_version='1.0.0',configuration={},configuration_hash='c'*64);db_session.add(h);db_session.flush()
    e=ResearchExperiment(hypothesis_id=h.id,experiment_type='historical_replay',status='completed',train_start=NOW-timedelta(days=60),train_end=NOW-timedelta(days=50),configuration={},configuration_hash='d'*64,experiment_version='1.0.0',hypothesis_version='1.0.0',hypothesis_configuration_hash=h.configuration_hash,sample_size=20,baseline_sample_size=20,result_metrics={},baseline_metrics={},comparison_metrics={},score=D('.7'),stability_score=D('.7'),data_quality_score=D('.8'),passed=True,failure_reasons=[],started_at=NOW-timedelta(days=60),completed_at=NOW-timedelta(days=50));db_session.add(e);db_session.flush()
    c=ResearchCandidateStrategy(name='c',description='d',source_hypothesis_id=h.id,source_experiment_id=e.id,candidate_version='1.0.0',symbol_scope={},timeframe_scope={},regime_scope={},feature_conditions={},entry_conditions={},exit_conditions={},risk_conditions={},parameter_overrides={},evidence_summary={},evaluation_metrics={},experiment_score=D('.7'),stability_score=D('.7'),data_quality_score=D('.8'),status='draft',configuration={},configuration_hash='e'*64,created_at=NOW-timedelta(days=60),updated_at=NOW-timedelta(days=60));db_session.add(c);db_session.commit()
    p=policy(db_session,['candidate_staleness'],minimum=1,candidate_id=c.id,thresholds={'candidate_staleness_seconds':86400});rows=ResearchMonitoringService(db_session).evaluate(p.id,now=NOW);assert rows and rows[0].trigger_type=='candidate_staleness'

def test_cooldown_creates_suppressed_changed_event(db_session):
    add_regime(db_session,0,'trending_bull');add_regime(db_session,1,'ranging');p=ResearchMonitoringService(db_session).create_policy(MonitoringPolicyCreate(name='cool',status='enabled',trigger_rules={'types':['regime_change']},minimum_sample_size=1,cooldown_seconds=3600,symbol_scope=['BTC/USDT']));svc=ResearchMonitoringService(db_session);a=svc.evaluate(p.id,now=NOW+timedelta(hours=2));assert a[0].status=='detected'
    add_regime(db_session,2,'breakout');b=svc.evaluate(p.id,now=NOW+timedelta(hours=2,minutes=10));assert b and b[0].status=='suppressed' and 'policy_cooldown' in b[0].warnings

def test_explicit_queue_auto_queue_default_false_and_idempotency(monkeypatch,db_session):
    monkeypatch.delenv('AI_MONITOR_AUTO_QUEUE_RESEARCH',raising=False);add_regime(db_session,0,'ranging');add_regime(db_session,1,'breakout');p=policy(db_session,['regime_change'],minimum=1);svc=ResearchMonitoringService(db_session);t=svc.evaluate(p.id,now=NOW+timedelta(hours=3))[0];assert t.research_job_id is None
    a=svc.queue_research(t.id);b=svc.queue_research(t.id);assert a.id==b.id and a.job_version==JOB_VERSION and a.status=='queued'

def test_auto_queue_true(monkeypatch,db_session):
    monkeypatch.setenv('AI_MONITOR_AUTO_QUEUE_RESEARCH','true');add_regime(db_session,0,'ranging');add_regime(db_session,1,'breakout');p=policy(db_session,['regime_change'],minimum=1);ResearchMonitoringService(db_session).evaluate(p.id,now=NOW+timedelta(hours=3));assert db_session.query(AdaptiveResearchJob).count()==1

def test_job_failure_sanitized_bounded_retry_and_cancel(monkeypatch,db_session):
    monkeypatch.setenv('AI_MONITOR_MAX_JOB_RETRIES','1');add_regime(db_session,0,'ranging');add_regime(db_session,1,'breakout');p=policy(db_session,['regime_change'],minimum=1);svc=ResearchMonitoringService(db_session);t=svc.evaluate(p.id,now=NOW+timedelta(hours=3))[0];j=svc.queue_research(t.id,'blueprint_revalidation');out=svc.process_job(j.id);assert out.status=='failed' and out.failure_reason=='research_job_error:ValueError' and out.retry_count==1
    out2=svc.process_job(j.id);assert out2.retry_count==2; assert svc.cancel_job(j.id).status=='cancelled'

def test_worker_cycle_bounded_and_heartbeat(monkeypatch,db_session):
    monkeypatch.setenv('AI_MONITOR_MAX_POLICIES_PER_CYCLE','1');monkeypatch.setenv('AI_MONITOR_MAX_TRIGGERS_PER_CYCLE','1');monkeypatch.setenv('AI_MONITOR_MAX_JOBS_PER_CYCLE','0')
    add_regime(db_session,0,'ranging');add_regime(db_session,1,'breakout');policy(db_session,['regime_change'],minimum=1);policy(db_session,['regime_change'],minimum=1,name='other')
    out=ResearchMonitoringService(db_session).worker_cycle('test-monitor');assert out['policies_evaluated']<=1 and out['triggers_detected']<=1
    st=db_session.get(ResearchMonitorWorkerStatus,'test-monitor');assert st and st.last_heartbeat and st.last_cycle_completed

def test_monitor_status_safe_metadata(db_session):
    policy(db_session,['regime_change']);data=ResearchMonitoringService(db_session).monitor_status();assert data['postgresql_authoritative'] and data['valkey_role']=='transient_coordination_only' and data['trading_activation'] is False and 'password' not in str(data).lower()

def test_observation_lifecycle(db_session):
    add_regime(db_session,0,'ranging');add_regime(db_session,1,'breakout');p=policy(db_session,['regime_change'],minimum=1);svc=ResearchMonitoringService(db_session);t=svc.evaluate(p.id,now=NOW+timedelta(hours=3))[0];svc.queue_research(t.id);svc.acknowledge(t.id);events={x.event_type for x in db_session.query(ResearchObservation)}
    assert {'ai_monitor_policy_created','ai_monitor_trigger_detected','ai_adaptive_research_job_queued','ai_monitor_trigger_acknowledged'}<=events

def test_trigger_vocabulary_and_route_inventory():
    assert {'regime_change','expectancy_degradation','shadow_performance_drift','candidate_staleness','research_portfolio_degradation'}<=TRIGGER_TYPES
    paths={r.path for r in router.routes};required={'/v1/research/ai/monitoring/policies','/v1/research/ai/monitoring/status','/v1/research/ai/monitoring/triggers','/v1/research/ai/adaptive-jobs'};assert required<=paths

def test_worker_is_separate_and_fastapi_has_no_monitor_loop():
    root=Path(__file__).resolve().parents[3];worker=(root/'services/research-monitor-worker/main.py').read_text();main=(root/'apps/api/main.py').read_text();assert 'while True' in worker and 'ResearchMonitoringService' in worker and 'while True' not in main

def test_pipeline_reuse_and_safety_source():
    src=inspect.getsource(__import__('packages.research.ai.monitoring',fromlist=['x'])).lower()
    for token in ['.orchestrator import airesearchorchestrator','.validation import blueprintvalidationservice','.evolution import strategyevolutionservice','.matching import strategymatchingservice','.shadow import shadowresearchservice']: assert token in src
    forbidden=['import ccxt','decrypt_credentials','withdraw','submit_order(','place_order(','start_bot(','stop_bot(','approve_demo(','approve_live(','allocate_capital(','bypass_risk('];assert all(x not in src for x in forbidden)

def test_policy_enable_is_not_trading_enable(db_session):
    p=policy(db_session,['regime_change']); assert p.status=='enabled'
    svc=ResearchMonitoringService(db_session)
    for x in ['start_bot','enable_strategy','allocate_capital','approve_demo','submit_order']:
        assert not hasattr(svc,x)
