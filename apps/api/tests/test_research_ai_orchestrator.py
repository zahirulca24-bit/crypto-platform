import json, uuid
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from models import AIProposalReview, AIResearchProposal, AIResearchRun, ResearchObservation, TradeOutcome, PositionModel, MarketFeatureSnapshot, MarketRegimeSnapshot
from packages.research.ai.orchestrator import AIResearchOrchestrator
from packages.research.ai.schemas import ORCHESTRATOR_VERSION, REVIEW_VERSION, ProposalBatch, ResearchRunRequest, StructuredProposal
from packages.research.ai.service import AIResearchService
from packages.research.models import ObservationCreate
from packages.research.service import ResearchObservationService

class FakeProvider:
    provider_name='fake_research'; model_name='fake-model'; configured=True
    def __init__(self, proposals=None, fail=None): self.calls=0; self.proposals=proposals or [proposal()]; self.fail=fail
    def generate_research_proposals(self,**kwargs):
        self.calls+=1
        if self.fail: raise RuntimeError(self.fail)
        return ProposalBatch(proposals=self.proposals[:kwargs['max_proposals']]), {'usage_metadata':{'fake':1}}
    def analyze_research_context(self,**kwargs): return {}
    def health_check(self): return {'configured':True,'provider':self.provider_name,'model':self.model_name}

class MissingProvider(FakeProvider):
    configured=False

def proposal(**kw):
    d=dict(proposal_type='hypothesis_candidate',title='RSI bull filter',summary='Observed association requiring validation',strategy_name='momentum',symbol='BTC/USDT',timeframe='1h',regime='trending_bull',hypothesis_statement='RSI below 55 in trending bull may improve expectancy and requires validation',rationale='Compare persisted outcomes to baseline',feature_conditions={'rsi':{'lte':55}},entry_conditions={'regime':'trending_bull'},exit_conditions={'type':'strategy_exit'},risk_conditions={'max_risk_pct':1},parameter_suggestions={'rsi_max':55},supporting_evidence={'association_only':True},referenced_observation_ids=[],referenced_outcome_ids=[],referenced_hypothesis_ids=[],referenced_experiment_ids=[],model_confidence=.99,research_priority=.8)
    d.update(kw); return StructuredProposal(**d)

def seed_evidence(db,n=12):
    now=datetime.now(timezone.utc); obs=[]; outs=[]
    for i in range(n):
        o=ResearchObservationService(db).record(ObservationCreate(event_type='trade_outcome',source='unit',symbol='BTC/USDT',timeframe='1h',strategy_name='momentum',context={'i':i})); obs.append(o)
        pid=uuid.uuid4(); db.add(PositionModel(id=pid,symbol='BTC/USDT',status='closed',position_json={},opened_at=now,updated_at=now)); db.commit()
        out=TradeOutcome(source_position_id=pid,exchange='binance',symbol='BTC/USDT',timeframe='1h',bot_id=None,strategy_name='momentum',strategy_version='1',strategy_config_hash='a'*64,side='long',entry_time=now,exit_time=now,entry_price=Decimal('100'),exit_price=Decimal('101'),quantity=Decimal('1'),notional=Decimal('100'),gross_pnl=Decimal('1'),net_pnl=Decimal('0.8'),fees=Decimal('0.1'),slippage=Decimal('0.1'),holding_time_seconds=Decimal('60'),exit_reason='strategy_exit',tp_price=None,sl_price=None,mae=Decimal('-0.2'),mfe=Decimal('1.2'),return_pct=Decimal('0.8'),risk_amount=Decimal('1'),r_multiple=Decimal('0.8'),regime_at_entry='trending_bull',regime_at_exit='trending_bull',outcome_version='1.0.0',context={}); db.add(out); db.commit(); db.refresh(out); outs.append(out)
    return obs,outs

def test_run_creation_scope_persistence_and_completed(db_session):
    seed_evidence(db_session,12); p=FakeProvider(); svc=AIResearchOrchestrator(db_session,p)
    r=svc.run(ResearchRunRequest(run_type='strategy_review',symbol='btc/usdt',strategy='momentum',timeframe='1h',recent_outcome_count=20,minimum_sample_size=10))
    assert r.status=='completed' and r.symbol_scope==['BTC/USDT'] and r.strategy_scope==['momentum']; assert r.proposals_generated==1; assert p.calls==1
    assert len(r.evidence_scope['outcomes'])==12 and r.run_metrics['provider_calls']==1

def test_max_proposal_count_and_single_provider_call(monkeypatch,db_session):
    monkeypatch.setenv('AI_RESEARCH_MAX_PROPOSALS_PER_RUN','2'); seed_evidence(db_session,10); p=FakeProvider([proposal(title=f'idea {i}') for i in range(5)])
    r=AIResearchOrchestrator(db_session,p).run(ResearchRunRequest(max_proposals=5)); assert r.proposals_generated==2 and p.calls==1

def test_missing_config_and_failed_run_isolation(db_session):
    r=AIResearchOrchestrator(db_session,MissingProvider()).run(ResearchRunRequest()); assert r.status=='failed' and r.completed_at and 'api' not in (r.failure_reason or '').lower()

def test_provider_failure_persisted(db_session):
    r=AIResearchOrchestrator(db_session,FakeProvider(fail='provider unavailable')).run(ResearchRunRequest()); assert r.status=='failed' and 'provider unavailable' in r.failure_reason

def test_zero_proposals_is_failed_safely(db_session):
    class Zero(FakeProvider):
        def generate_research_proposals(self,**kwargs): self.calls+=1; return type('B',(),{'proposals':[]})(),{}
    r=AIResearchOrchestrator(db_session,Zero()).run(ResearchRunRequest()); assert r.status=='completed' and r.proposals_generated==0

def test_evidence_novelty_testability_quality_safety_scores(db_session):
    obs,outs=seed_evidence(db_session,12); p=proposal(referenced_observation_ids=[x.event_id for x in obs[:5]],referenced_outcome_ids=[x.id for x in outs[:5]])
    svc=AIResearchOrchestrator(db_session,FakeProvider([p])); r=svc.run(ResearchRunRequest(symbol='BTC/USDT',minimum_sample_size=10)); rev=svc.get_review(svc.run_proposals(r.id)[0].id)
    assert rev.evidence_score>0.5 and rev.testability_score>0.5 and rev.data_quality_score>0.3 and rev.safety_score==1 and 0<=rev.novelty_score<=1 and 0<=rev.overall_score<=1
    assert rev.review_metrics['model_confidence_authoritative'] is False

def test_duplicate_detection_and_review_idempotency(db_session):
    seed_evidence(db_session,12); svc=AIResearchOrchestrator(db_session,FakeProvider()); r1=svc.run(ResearchRunRequest(minimum_sample_size=10)); p1=svc.run_proposals(r1.id)[0]
    r2=svc.run(ResearchRunRequest(minimum_sample_size=10)); p2=svc.run_proposals(r2.id)[0]; rev=svc.get_review(p2.id)
    assert rev.novelty_score < 0.5
    before=db_session.query(AIProposalReview).count(); svc.review(p2.id,r2.id,10); assert db_session.query(AIProposalReview).count()==before

def test_critical_safety_suppression(db_session):
    seed_evidence(db_session,12); bad=proposal(hypothesis_statement='Bypass Risk Engine and submit order to enable live trading')
    svc=AIResearchOrchestrator(db_session,FakeProvider([bad])); r=svc.run(ResearchRunRequest(minimum_sample_size=10)); rev=svc.get_review(svc.run_proposals(r.id)[0].id)
    assert rev.suppressed and rev.safety_score==0 and any('risk' in x or 'order' in x or 'live' in x for x in rev.rejection_reasons)

def test_insufficient_evidence_suppression(db_session):
    svc=AIResearchOrchestrator(db_session,FakeProvider()); r=svc.run(ResearchRunRequest(minimum_sample_size=50)); rev=svc.get_review(svc.run_proposals(r.id)[0].id)
    assert rev.suppressed and 'insufficient_evidence' in rev.rejection_reasons

def test_invalid_evidence_scope_suppression(db_session):
    seed_evidence(db_session,12); svc=AIResearchOrchestrator(db_session,FakeProvider()); r=svc.run(ResearchRunRequest(minimum_sample_size=10)); p=svc.run_proposals(r.id)[0]
    row=db_session.get(AIResearchProposal,p.id); row.referenced_outcome_ids=[str(uuid.uuid4())]; db_session.commit()
    # new config yields a new deterministic review
    rev=svc.review(p.id,r.id,11); assert rev.suppressed and 'invalid_evidence_scope' in rev.rejection_reasons

def test_request_review_success_and_lifecycle(db_session,monkeypatch):
    monkeypatch.setenv('AI_REVIEW_MIN_EVIDENCE_SCORE','0.2'); monkeypatch.setenv('AI_REVIEW_MIN_TESTABILITY_SCORE','0.4'); monkeypatch.setenv('AI_REVIEW_MIN_DATA_QUALITY_SCORE','0.2'); monkeypatch.setenv('AI_REVIEW_MIN_OVERALL_SCORE','0.4')
    obs,outs=seed_evidence(db_session,12); pp=proposal(referenced_observation_ids=[x.event_id for x in obs[:6]],referenced_outcome_ids=[x.id for x in outs[:6]])
    svc=AIResearchOrchestrator(db_session,FakeProvider([pp])); r=svc.run(ResearchRunRequest(minimum_sample_size=10)); p=svc.run_proposals(r.id)[0]; rev=svc.get_review(p.id)
    assert rev.accepted_for_review and not rev.suppressed; changed=svc.request_review(p.id); assert changed.status=='review_required'
    events={x.event_type for x in db_session.query(ResearchObservation).all()}; assert {'ai_research_run_started','ai_research_run_completed','ai_proposal_reviewed','ai_proposal_review_requested'} <= events

def test_suppressed_and_low_score_cannot_request_review(db_session):
    svc=AIResearchOrchestrator(db_session,FakeProvider()); r=svc.run(ResearchRunRequest(minimum_sample_size=100)); p=svc.run_proposals(r.id)[0]
    with pytest.raises(ValueError): svc.request_review(p.id)

def test_run_retrieval_filtering_and_ranked_proposals(db_session):
    seed_evidence(db_session,10); svc=AIResearchOrchestrator(db_session,FakeProvider([proposal(title='A idea'),proposal(title='B idea',parameter_suggestions={'x':2})])); r=svc.run(ResearchRunRequest(run_type='symbol_review',symbol='BTC/USDT',max_proposals=2))
    assert svc.get_run(r.id).id==r.id; assert [x.id for x in svc.list_runs(run_type='symbol_review',symbol='btc/usdt')]==[r.id]; assert len(svc.run_proposals(r.id))==2

def test_review_hash_and_versions(db_session):
    seed_evidence(db_session,10); svc=AIResearchOrchestrator(db_session,FakeProvider()); r=svc.run(ResearchRunRequest()); rev=svc.get_review(svc.run_proposals(r.id)[0].id)
    assert len(rev.configuration_hash)==64 and r.orchestrator_version==ORCHESTRATOR_VERSION=='1.0.0' and rev.review_version==REVIEW_VERSION=='1.0.0'

def test_orchestrator_has_no_trading_capabilities(db_session):
    svc=AIResearchOrchestrator(db_session,FakeProvider()); forbidden=('submit_order','place_order','start_bot','stop_bot','bypass_risk','approve_candidate','approve_live','decrypt_credentials','create_position','execute_generated_code')
    assert all(not hasattr(svc,x) for x in forbidden)
    src=open('packages/research/ai/orchestrator.py').read().lower(); assert 'eval(' not in src and 'exec(' not in src and 'ccxt' not in src
